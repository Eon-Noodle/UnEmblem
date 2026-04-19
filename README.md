**UnEmblem** is a GBA Fire Emblem-style fangame based on the story of the manga series *Undead Unluck*.

![TitleScreen](/utilities/unemblem_readme/title_screen.png)
![AOE](/utilities/unemblem_readme/greyscale.png)
![ActivatedSkill](/utilities/unemblem_readme/roundtable.png)

## Game Engine - Lex Talionis

> **Lex Talionis** was originally released without a dedicated graphical editor, which meant all game creation was done through modification of text files and xml files. But no longer!
>
> **LT-maker** is the easy-to-use but powerful editor built on top of the **Lex Talionis** engine. The **Lex Talionis** engine itself has been completely rewritten using the knowledge gained over seven years of development to be faster, better, and easier-to-use. You can create a whole new game without touching any code.

**Lex Talionis** is a powerful game maker for producing pixel art games in the style of GBA Fire Emblem. This repository began as a fork of the LT-maker repository and has since been modified.

<p>
  <span style="display: inline-block; width: 120px;"><strong>Website:</strong></span> <a href="https://lex-talionis.net/"><img src="https://img.shields.io/badge/Lex%20Talionis-Visit-0f1533?logo=dotnet"></a><br>
  <span style="display: inline-block; width: 120px;"><strong>Repository:</strong></span> <a href="https://gitlab.com/rainlash/lt-maker"><img src="https://img.shields.io/badge/Gitlab-Explore-FC6D26?logo=gitlab&logoColor=white"></a><br>
  <span style="display: inline-block; width: 120px;"><strong>Documentation:</strong></span> <a href="https://lt-maker.readthedocs.io/en/latest/"><img src="https://img.shields.io/badge/Read%20the%20Doc-Browse-2980B9?logo=readthedocs"></a><br>
  <span style="display: inline-block; width: 120px;"><strong>Discord Server:</strong></span> <a href="https://discord.gg/dC6VWGh4sw"><img src="https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white"></a>
</p>

# Installation Guides
<details>
  <summary>For WINDOWS</summary> 

1) Download `UnEmblem.zip` from the [latest release](https://github.com/Eon-Noodle/UnEmblem/releases/latest).

2) Extract the game folder from the .zip/archive file and store it in any folder you wish. **!!AS LONG AS THAT FOLDER IS NOT BACKED UP BY ONEDRIVE OR OTHER CLOUD STORAGE!!**

3) Double-click `unemblem.exe` or `double_click_to_play.bat` to start the game. Both options do the same thing.
</details>

<details>
    <summary>For LINUX - PROTON (No terminal required, recommended)</summary>

1) Download `UnEmblem.zip` from the [latest release](https://github.com/Eon-Noodle/UnEmblem/releases/latest).

2) Extract the game folder from the .zip/archive file and store it in any folder you wish. **!!AS LONG AS THAT FOLDER IS NOT BACKED UP BY ONEDRIVE OR OTHER CLOUD STORAGE!!**

3) Install the Steam client via your preferred package manager or from the Steam website.

4) In the lower left corner of your Steam library, click the **"Add a Game"** button, and select **"Add a non-Steam game..."**.

5) Click **"Browse..."**, navigate to the folder where you stored the game, and select `unemblem.exe`. Then, click **"Add selected programs"** and the game now shows up in your Steam library.
</details>

<details>
    <summary>For LINUX - WINE (Requires terminal)</summary>

1) Download `UnEmblem.zip` from the [latest release](https://github.com/Eon-Noodle/UnEmblem/releases/latest).

2) Extract the game folder from the .zip/archive file and store it in any folder you wish. **!!AS LONG AS THAT FOLDER IS NOT BACKED UP BY ONEDRIVE OR OTHER CLOUD STORAGE!!**

3) Install your preferred version of Wine from the [WineHQ website](https://www.winehq.org/).
    - It is recommended to install Wine manually, as the package distributed by many package managers are outdated. Version 11.0 is known to run LT games in a stable manner. Older versions are untested.

4) Open `unemblem.exe` with Wine.
</details>

<details>
    <summary>For LINUX - Build from Source (Requires terminal)</summary>

1) Install the following programs (preferred versions if possible);
    ```
    python==3.11*
    python3pip
    pygame-ce==2.3.2
    pyinstaller==6.2.0
    typing-extensions==4.8.0
    PyQt5==5.15.10**
    mypy==1.8.0
    mypy-extensions==1.0.0
    ```
    - LT is potentially unstable or will not boot on newer versions of python. While there have been little to no reports of major issues on Linux specifically, do keep that in mind.
    - Some Linux distributions (mainly Ubuntu and Ubuntu-based distributions) may have trouble installing PyQt5. In that case, try: `sudo apt-get install python3-pyqt5`

2) Clone this repository to your prefered storage location: `git clone https://github.com/Eon-Noodle/UnEmblem.git`

3) Open a terminal window in the ``unemblem\` folder and type: `python3 run_engine.py`. The engine should now boot up with the desired game. 
    - You can also create a script to perform this command. It is recommended to run this script in the terminal, as the game uses the terminal as a log.
    - If the desired game does not boot up, change the command to `python3 run_editor.py`, click the **"Open other"** button and select the **"UnEmblem.ltproj"** folder. Once the editor opens, click the play icon in the icon bar and then select the **"Test Full Game..."** option. From there, you can play as normal.
</details>

<details>
    <summary>For MAC</summary>

1) Clone this repository to your prefered storage location;
    ```
    git clone https://github.com/Eon-Noodle/UnEmblem.git
    ```
2) Install Homebrew;
    ```
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```
3) Install Wine;
    ```
    brew install wine-stable
    ```
4) Install Miniconda;
    ```
    brew install --cask miniconda
    ```
5) Initialize conda in your shell;
    ```
    conda init "$(basename "${SHELL}")"
    ```
6) Perform the following steps before first boot;
    ```
    cd unemblem
    conda create -n fe-i-lt python=3.11.7
    conda activate fe-i-lt
    ```
7) Setup Windows Python;
    ```
    curl -O https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe
    wine python-3.11.7-amd64.exe
    ```
8) Install the following requirements **in Wine Python**;
    ```
    wine pip install -r
    python3pip
    pygame-ce==2.3.2
    pyinstaller==6.2.0
    typing-extensions==4.8.0
    PyQt5==5.15.10
    mypy==1.8.0
    mypy-extensions==1.0.0
    ```
9) Execute the following commands;
    ```
    cd unemblem
    conda activate fe-i-lt
    wine python run_engine.py
    ```
    * If the desired game does not boot up, change the last command to `wine python run_editor.py`, click the **"Open other"** button and select the **"UnEmblem.ltproj"** folder. Once the editor opens, click the play icon in the icon bar and then select the **"Test Full Game..."** option. From there, you can play as normal.
</details>

<details>
    <summary>For ANDROID</summary>

*The installing guide for Android is written from my experience following [this post](https://feuniverse.us/t/lex-talionis-on-android-its-time/28374) by Eretein. Thank you, Eretein.*

1) Open **File Manager**, in **Internal Storage**, create a new folder preferably named `Winlator`. Then inside that new folder:
    * Create two new files: `.nomedia` and `.nosearch`. If there is no option for creating new file, you can copy any two files (preferably not too heavy) into the `Winlator` folder, then rename them completely to be `.nomedia` and `.nosearch`.
    * Create an empty folder named `D`.

2) Download the `LTPad.7z` from Eretein's [LTPad presets](https://drive.google.com/file/d/1BzKX2e9yMgItAv_FaxvSura7KANut0tM/view?usp=sharing). Move it to the **Internal Storage → Winlator → D** folder and extract.

3) Download `UnEmblem.zip` from the [latest release](https://github.com/Eon-Noodle/UnEmblem/releases/latest). Move it to the **Internal Storage → Winlator → D** folder.

4) Make sure you have a Winrar for Android. I use **RAR by RARLAB** from [Google Play Store](https://play.google.com/store/apps/details?id=com.rarlab.rar&hl=en). Using the Winrar app, extract `UnEmblem.zip` into its own folder (`D\UnEmblem\`)

5) Download the APK file (named something like `Winlator.apk`) from [GitHub Releases](https://github.com/brunodev85/Winlator/releases).

6) Install the app by running the APK file.
    * If the installation because of Google Play Protect, be assured that it is not a malware. Apps outside of the Google Play Store are often flagged, so you will need to turn off Google Play Protect:
        1) Open the **Google Play Store** app
        2) Tap your profile icon (top right) → **Play Protect → Settings** (gear icon).
        3) Toggle off **"Scan apps with Play Protect"**.
        4) Run the `Winlator.apk` again.

7) Open the newly installed **Winlator** app. It might take a while upon first loading, just wait for it to finish.

8) In the **Containers** tab (should be by default), create a new container by pressing the **+** key.
    * Preferably name it `LTEmu`.
    * Set **Screen Size** to **"Custom"** with width and height being **480x320**.
    * Set **Audio Driver** to **"PulseAudio"**.
    * In the **Drives** tab, make a single drive **"D:"**. Click the **Browse** icon next to the Trash Can. Select **"Open Directory"**, navigate to **Internal Storage → Winlator → D** folder and click **Use this folder**.
    * In the **Advanced** tab, set **Box64 Preset** to **"Performance"** and set **Startup Selection** to **"Aggressive"**.
    * Click the big tick button (bottom right) to finish making the container.

9) Still inside **Winlator** app, click on the **Menu** button (top left) and switch to the **Input Controls** tab. Click **Import Profile → Open File** then navigate to **Internal Storage → Winlator → D → LTPad** folder and select `winlator_LTPad.icp`.

10) Inside **Winlator** app, click on the **Menu** button (top left) and switch to the **Settings** tab. Set **Box64** Preset to **"Performance"**. Click the big tick button (bottom right) to save the edits.

11) Switch back to the **Containers** tab, open `LTEmu` container menu by clicking its **⋮** button (three dots).
    * Select **"File Manager"**.
    * Click on the **Browse** button (next to the three dots **⋮** Menu button) of `Drive D:`.
    * Click on the **⋮** button (three dots) of the `UnEmblem` folder and select **Cut**.
    * Go back to the **"File Manager"** root.
    * Click on the **Browse** button of `Drive C:`.
    * Click on the **Paste** button (bottom right) to move the `UnEmblem` folder here.

12) Now, to play the game, from the Android device:
    * Open **Winlator** app.
    * In the **Containers** tab, click on the **⋮** button of the `LTEmu` container, select **"File Manager"**.
    * Click on the **Browse** button of `Drive C:`.
    * Click on the **Browse** button of the `UnEmblem` folder.
    * Click on the **Browse** button of the inner `unemblem` folder.
    * Click on the **Play** button of the `double_click_to_play.bat` file. This will launch the Window emulation and start the game.

13) If the game doesn’t launch after an eternity, you’ll have to tweak settings until it runs:
    * In the `LTEmu` container setting (by clicking on the **⋮** button and select **Edit**), try out other **Graphics Driver** options.
    * If none works, still in the container setting, under the **Advanced** tab, try out other **Box64 Preset** options.

14) After the game has finished loading, press your device’s **Back** button, the main menu of Winlator will pop up. Inside the **"Input Controls"** tab. From the dropdown, select `LTPad`, and tick **Touchscreen Controls** and **Relative Mouse Movement**.
    * If you have a controller, you don’t need the onscreen controls. You’ll have to connect your controller and set it up in the **Input Controls** screen. The controller **must** be connected **before** the game is launched, else it won’t be detected.
</details>

<details>
    <summary>For IOS</summary>

Tough luck lol
</details>

## Default Controls

|Function   | Keyboard | Mouse | Xbox Controller | PS Controller|
|-----------|----------|-------|-----------------|--------------|
|Select     | X        | Left  | A               | Cross        |
|Back       | Z        | Right | B               | Circle       |
|Info       | C        | Middle| X               | Square       |
|AUX        | A        |       | Back            | Share        |
|Move       | Arrows   | Hover | Left Stick      | Left Stick   |
|Start      | S        |       | Start / Y       | Options / Triangle |
|Screenshot | ` / F12  |       |                 |              |

* The **AUX** key is used to focus the cursor on your units when on the map, to toggle the Growth Rate display on the Unit Info Menu and to show more pages for item/skill descriptions if they have more than one page.
* Screenshots are saved as `.png` files if **F12** was pressed or `.bmp` files if **`** key was pressed and held. Screenshots are saved within the game folder.
* You can soft reset by holding **Select, Back, and Start**.
* You can rebind which key on your keyboard does what in the **Options > Controls** menu in-game. Controller button remapping has not been implemented yet, although you can use an input remapper to bind controller input to keyboard keys as a workaround.

## Known Issues
* Windows Defender and other common anti-virus programs do not like LT-Maker games. Just choose to run the game anyway and/or make it an exception for Windows Defender.

* The EXP gain SFX may sound weird on some computers. (The pitch is sound card dependent.) To adjust this, go into `saves/config.ini`. Change sound_buffer_size to a small even number until the SFX sounds right. **Make sure to close the game while editing these settings, and to save the file after editing it.**

## Carrying Over Save Files

If the game gets an update and you would like to transfer your saves from an old version to a new version, follow these steps:

1) Open the `UnEmblem\` folder of the older version.
2) Open the `saves\` folder.
3) Move all the files within the saves folder into the saves folder of the newer version.
4) Restart the chapter to ensure the changes are implemented.

## Tips and Tricks

* You can change the screen size in-game through **Extras > Options > Config > Screen Size** or using mouse, hold and drag a corner of the screen.
    * The full-screen option is wonky and not recommended.

* You can toggle mouse controls in-game through **Extras > Options > Config > Mouse**

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
