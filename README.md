# Idle Dentistry

A terminal idle game about turning a broom cupboard into the Molar Empire. Treat patients, hire staff, and upgrade your clinic! Built in Python for [HackClub](https://hackclub.com/)'s [wrong tool](https://wrong.hackclub.com/) program.

![screenshot](https://cdn.hackclub.com/01a15631-a9c4-7d33-9512-5d9a5c70fa7d/image.png)

## How to play

Download and extract the project, then open a terminal in the folder containing `main.py`.

Use Python 3.12 or newer and an interactive terminal. The needs at least 60 columns x 22 rows. Having a larger window leaves more room for descriptions and title art. You can also use the integrated terminal in a code editor (but honestly why would you).

### Linux / macOS

```sh
python3 main.py
```

The game uses Pytohn's standard library, included `curses`, on these platforms.

### Windows

Install the dependencies then launch the game:

```powershell
python -m pip install -r requirements.txt
python main.py
```

`requirements.py` installs [windows-curses](https://pypi.org/project/windows-curses/). The game also includes a native Windows console input backend. Because I developed this primarily in Linux, there may be some errors in the Windows version. I didn't want to exclude a Windows release, so I tried my hardest to add support for it. If there are any bugs please let me know!

On a fresh save, the main menu will ask if you want to Continue, start a New Game, Replay Tutorial, edit Settings or Quit. Once a save exists, launching the game opens directly into the most recently saved slot. There are three (3) save slots.

You can use `python3 main.py --menu` to open the menu instead, or just press `M` anytime during play. On Windows replace `python3` with `python`.

## Basic gameplay

1. Start the tutorial and treat patients on the Clinic page. Follow the prompts, use `SPACE` (or mouse click on certain terminals) to treat patients.
2. Open the Staff page with `F` and hire your first dentist for $25. These are your source of passive income. It is an idle game after all.
3. Open Contracts with `O` to claim completed goals, and Cases with `A` to accept patients for rewards.
4. After 10 manual treatments, press X to activate Focus mode. You can also craft equipment in the Workshop with W.
5. Save up to expand your clinic. Once you have enough, press `E` to unlock a new clinic with boosted rewards.
6. Prestige once you earn $100,000 in a run. Prestiging resets your progress, but you get stars that you can use to get new boosts and upgrades.

## What's in the game?

- There are five clinics, four staff types and three upgrade types.
- Completing cases gives you cabinet keys. You can use them to open supply cabinets for materials and cash.
- Materials can be used to craft equipment.
- The prestige system allows you to unlock nine skills that offer different upgrades for various aspects of the game, like treatment, management and expansion.
  - Prestiging resets almost everything. You keep:
    - Stars,
    - Skills,
    - Achievements,
    - Contracts,
    - Crafted equipment,
    - Collected cosmetics
- Fifty cosmetic items with their own ASCII artwork. You can get supply crates and crate keys by actively playing the game, i.e. treating patients. There is a 5% chance for one to drop every time you treat a patient.
  - You can view cosmetics in the collection, and put your favourite one on display in the clinic.
  - Cosmetics give no stat bonuses. I added them because unboxing stuff is cool lol.

## Controls

Each page shows its controls. I'm not gonna list them all out here because it'd be unnecessarily long. You can also change controls through the settings menu in-game.

## Saves and settings

Progress saves every 15 seconds, on important actions, and when returning to the menu or quitting. Invalid data is rejected, and a valid `.bak` save can recover progress if the primary file cannot be read.

By default, these files are created beside `main.py`:

- `save.json`, `save-slot2.json`, `save-slot3.json`: for the three slots.
- `save-settings.json`: shared controls and display preferences.
- `.bak`, `.lock` and timestamped archive files: backups, session locks and archived saves.

To use another save location:

```sh
python3 main.py --save /path/to/clinic.json
```

The other slots and settings use that filename as their prefix. `--play` opens slot 1 directly, and `--menu` forces the menu. These two options are mutually exclusive.

## Troubleshooting and development

You should not be able to hold a key to repeat its input. That ruins the fun of an idle clicker. However, this can happen on your host, so if you want you can launch with `--safe-input` to require the treatment key followed by Enter. Or don't. It's up to you.

`--no-color` disables colours for the session.

If the window is too small, resize it. If Python cannot import `curses` on Linux/macOS, use a Python installation with curses support; on Windows, install the requirements above.

These commands work without opening the game UI:

```sh
python3 main.py --version
python3 main.py --check-cosmetics
python3 simulate_balance.py --seconds 3600 --taps-per-second 0.5
```

The simulator compares three buying strategies and reports when they reach expansion and prestige milestones. It estimates progression rather than measuring a player's actual play time. Add `--csv balance-results.csv` to export its results, or `--baseline` to compare without Focus, crafting and Cabinet searches. This feature was added to test balance when I was looking at progression.

Cosmetics live in `data/cosmetics.json`. Each item has a stable key, name, rarity, description and up to four lines of ASCII artwork, each at most 14 characters wide. You can add your cosmetics if you wish. Use `--check-cosmetics` after editing. Disabling an item stops new drops; already owned copies remain available. The catalogue's `version: 1` describes its own data format.
