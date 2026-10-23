import argparse
import asyncio
import logging
import os
from pathlib import Path
import signal
import sys

LOG = logging.getLogger("dentistry.ssh")

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).with_name(".ssh-server"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the host key and print its fingerprint")
    add = commands.add_parser("add-player", help="Register a player's public key")
    add.add_argument("name")
    add.add_argument("public_key", type=Path)
    commands.add_parser("players", help="List registered players and key fingerprints")
    server = commands.add_parser("serve", help="Start the game server")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8022)
    server.add_argument("--max-players", type=int, default=8)
    server.add_argument("--idle-minutes", type=int, default=30)
    server.add_argument("--max-accounts", type=int, default=1000,
                        help="Stop self-registration at this many accounts (default: 1000)")
    server.add_argument("--closed-registration", action="store_true",
                        help="Only allow players registered by the administrator")
    args = parser.parse_args()
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535.")
        if not 1 <= args.max_players <= 64:
            parser.error("Max players must be between 1 and 64.")
        if not 1 <= args.idle_minutes <= 1440:
            parser.error("Idle minutes must be between 1 and 1440.")
        if not 1 <= args.max_accounts <= 100000:
            parser.error("Max accounts must be between 1 and 100000.")
    return args

async def serve(accounts, args):
    import asyncssh
    from platform_support import save_lock
    from ssh_terminal import GameTerminal
    from ssh_accounts import SignupLimiter

    active = set()
    connections = set()
    handlers = set()
    stopping = asyncio.Event()
    signups = SignupLimiter()

    class GameServer(asyncssh.SSHServer):
        def connection_made(self, connection):
            self.connection = connection
            self.key = None
            if stopping.is_set() or len(connections) >= args.max_players * 4:
                connection.close()
            else:
                connections.add(connection)

        def connection_lost(self, exc):
            connections.discard(self.connection)

        def begin_auth(self, username):
            self.key = accounts.public_key(username)
            self.can_register = not args.closed_registration and accounts.available(username)
            self.candidate_key = None
            return True

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            allowed = key == self.key if self.key is not None else self.can_register
            self.candidate_key = key if allowed else None
            return allowed

        def auth_completed(self):
            self.connection.set_extra_info(player_key=self.candidate_key)

    def refuse(process, message):
        process.stderr.write((message + "\r\n").encode())
        process.exit(1)

    async def play(process):
        username = process.get_extra_info("username")
        if process.command is not None or process.subsystem is not None:
            refuse(process, "This server runs Idle Dentistry. Connect without a remote command.")
            return
        if not process.term_type:
            refuse(process, "A terminal is required. Connect using ssh -t.")
            return
        if stopping.is_set():
            refuse(process, "The server is shutting down. Please reconnect later.")
            return
        if username in active:
            refuse(process, "Your clinic is already open. Close the other session first.")
            return
        if len(active) >= args.max_players:
            refuse(process, "Max player count reached. Try again later!")
            return

        key = process.get_extra_info("player_key")
        try:
            if key is None:
                raise ValueError("Connect with your player SSH key")
            current = accounts.public_key(username)
            if current is not None:
                if current != key:
                    raise ValueError("That player name is already registered to another key.")
            else:
                if args.closed_registration:
                    raise ValueError("Self-registration is closed right now :(")
                address = process.get_extra_info("peername", ("unknown",))[0]
                if not signups.allowed(address):
                    raise ValueError("Signup limit reached. Please try again in a while.")
                if accounts.register(username, key, args.max_accounts):
                    signups.record(address)
                    LOG.info("Registered player %s", username)
        except RuntimeError:
            refuse(process, "Registration is busy right now. Please reconnect later.")
            return
        except ValueError as exc:
            refuse(process, str(exc))
            return
        except OSError:
            LOG.exception("Could not register player %s", username)
            refuse(process, "Could not save your account right now :( try again later...")
            return
        
        active.add(username)
        handler = asyncio.current_task()
        handlers.add(handler)
        terminal = None
        tasks = []
        status = 1
        reason = "disconnected"
        last_input = asyncio.get_running_loop().time()

        async def receive_input():
            nonlocal last_input
            while True:
                try:
                    data = await process.stdin.read(8192)
                except asyncssh.TerminalSizeChanged as exc:
                    terminal.resize(exc.term_size)
                    continue
                except (asyncssh.SignalReceived, asyncssh.BreakReceived):
                    return "client requested exit"
                if not data:
                    return "disconnected"
                last_input = asyncio.get_running_loop().time()
                await terminal.write(data)

        async def send_output():
            connected = True
            while data := await terminal.read():
                if connected:
                    try:
                        process.stdout.write(data)
                        await process.stdout.drain()
                    except (OSError, asyncssh.Error):
                        connected = False
            return "game closed"

        async def check_idle():
            while True:
                await asyncio.sleep(1)
                if stopping.is_set():
                    return "server shutdown"
                if asyncio.get_running_loop().time() - last_input >= args.idle_minutes * 60:
                    return "idle timeout"

        try:
            terminal = await GameTerminal.start(
                accounts.save_path(username), process.term_type, process.term_size)
            LOG.info("%s connected", username)
            tasks = [asyncio.create_task(receive_input()),
                     asyncio.create_task(send_output()),
                     asyncio.create_task(check_idle()),
                     asyncio.create_task(terminal.child.wait())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                result = task.result()
                if isinstance(result, str):
                    reason = result
        except (OSError, ValueError, asyncssh.Error) as exc:
            LOG.warning("%s session ended: %s", username, exc)
        finally:
            for index, task in enumerate(tasks):
                if index != 1:
                    task.cancel()
            if terminal:
                status = await terminal.stop()
                if len(tasks) > 1:
                    try:
                        await asyncio.wait_for(asyncio.shield(tasks[1]), timeout=1)
                    except (asyncio.TimeoutError, OSError, asyncssh.Error):
                        pass
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                terminal.close()
            active.discard(username)
            handlers.discard(handler)
            LOG.info("%s left (%s, exit %s)", username, reason, status)
            try:
                process.stdout.write(f"\r\nClinic closed: {reason}.\r\n".encode())
                process.exit(0 if status == 0 else 1)
            except (OSError, asyncssh.Error):
                pass
    
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopping.set)
    try:
        with save_lock(accounts.directory / "server"):
            listener = await asyncssh.listen(
                args.host, args.port, server_factory=GameServer,
                server_host_keys=[accounts.host_key], config=None,
                process_factory=play, encoding=None, line_editor=False,
                public_key_auth=True, password_auth=False, kbdint_auth=False,
                host_based_auth=False, gss_auth=False, gss_kex=False,
                agent_forwarding=False, x11_forwarding=False,
                sftp_factory=None, allow_scp=False,
                login_timeout=20, keepalive_interval=30, keepalive_count_max=3,
            )
            try:
                LOG.info("Listening on %s:%s (up to %s players)", args.host, args.port, args.max_players)
                await stopping.wait()
            finally:
                listener.close()
                stopping.set()
                LOG.info("Saving active clinics...")
                if handlers:
                    await asyncio.gather(*tuple(handlers), return_exceptions=True)
                closing = tuple(connections)
                for connection in closing:
                    connection.close()
                await asyncio.gather(*(c.wait_closed() for c in closing), return_exceptions=True)
                await listener.wait_closed()
    finally:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)

def main():
    args = parse_args()
    if sys.platform != "linux":
        print("Host this server on Linux (or WSL). Windows and macOS can connect as players.", file=sys.stderr)
        return 1
    try:
        import asyncssh
        from ssh_accounts import Accounts
    except ImportError:
        print("Install server dependencies: python -m pip install -r requirements-ssh.txt", file=sys.stderr)
        return 1
    os.umask(0o077)
    accounts = Accounts(args.data_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    try:
        if args.command == "init":
            print("Server fingerprint:", accounts.initialise())
        elif args.command == "add-player":
            print(f"Added {args.name}:", accounts.add(args.name, args.public_key))
        elif args.command == "players":
            for name, fingerprint in accounts.players():
                print(name, fingerprint)
        else:
            if not accounts.host_key.is_file():
                raise ValueError("Run python ssh_server.py init first.")
            print("Server fingerprint:", asyncssh.read_private_key(accounts.host_key).get_fingerprint(), flush=True)
            asyncio.run(serve(accounts, args))
    except (OSError, ValueError, RuntimeError, asyncssh.Error) as exc:
        print(f"Server error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())