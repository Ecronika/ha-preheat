# Anleitung zur Veröffentlichung auf GitHub und HACS

Da auf diesem System `git` nicht installiert ist, müssen wir zunächst die Voraussetzungen schaffen. Diese Anleitung führt dich Schritt für Schritt durch den Prozess, deinen Code zu veröffentlichen und HACS-fähig zu machen.

## Schritt 1: Git installieren

Um Dateien zu GitHub hochzuladen, benötigst du das Versionsverwaltungstool **Git**.

1.  Lade Git für Windows herunter: [https://git-scm.com/download/win](https://git-scm.com/download/win)
2.  Installiere es. Die Standardeinstellungen sind in Ordnung.
3.  Öffne nach der Installation ein **neues** Terminal (Eingabeaufforderung oder PowerShell), damit der Befehl `git` erkannt wird.
    >   **Wichtig:** Wenn du VS Code verwendest, musst du es oft **komplett neu starten** (schließen und wieder öffnen), damit die neue Installation erkannt wird.
4.  Konfiguriere deinen Namen und deine E-Mail-Adresse (diese erscheinen in den Änderungen):
    ```powershell
    git config --global user.name "Dein Name"
    git config --global user.email "deine@email.com"
    ```

## Schritt 2: GitHub Repository erstellen

1.  Gehe auf [GitHub.com](https://github.com) und melde dich an.
2.  Klicke oben rechts auf das **+** und wähle **New repository**.
3.  Gib dem Repository einen Namen (z.B. `ha-preheat`).
    *   *Tipp:* Der Name sollte idealerweise mit dem in deiner Dokumentation übereinstimmen.
4.  Wähle **Public** (HACS benötigt ein öffentliches Repository).
5.  Lasse die Checkboxen für README, .gitignore und License **leer** (wir haben diese Dateien schon lokal).
6.  Klicke auf **Create repository**.
7.  Kopiere die URL deines neuen Repositories (z.B. `https://github.com/DeinUser/ha-preheat.git`).

## Schritt 3: Lokales Projekt hochladen

Gehe zurück in dein Terminal in diesen Ordner (`c:\Users\tpaul\.gemini\antigravity\scratch\ha_custom_component`).

Führe folgende Befehle nacheinander aus:

1.  **Repository initialisieren:**
    ```powershell
    git init
    ```

2.  **Alle Dateien hinzufügen:**
    ```powershell
    git add .
    ```

3.  **Ersten Stand sichern (Commit):**
    ```powershell
    git commit -m "Initial release v2.2.0"
    ```

4.  **Verbindung zu GitHub herstellen** (füge hier deine kopierte URL ein):
    ```powershell
    git remote add origin https://github.com/DeinUser/ha-preheat.git
    ```
    *(Falls du den Namen ändern musst: `git remote set-url origin <NEUE_URL>`).*

5.  **Code hochladen:**
    ```powershell
    git branch -M main
    git push -u origin main
    ```
    *Du wirst eventuell nach deinen GitHub-Zugangsdaten gefragt.*

## Schritt 4: Ein Release erstellen (Wichtig für HACS)

HACS schaut nach "Releases", um Versionen zu verwalten.

1.  Gehe auf deine neue Repository-Seite auf GitHub.
2.  Klicke auf der rechten Seite auf **Releases** und dann auf **Draft a new release**.
3.  **Choose a tag**: Erstelle einen neuen Tag, z.B. `v2.2.0`.
    *   *Wichtig:* Dieser Versionstag muss mit der `version` in deiner `manifest.json` übereinstimmen!
4.  **Release title**: `v2.2.0 - Intelligent Preheating`.
5.  **Description**: Du kannst hier den Inhalt aus deiner `CHANGELOG.md` einfügen.
6.  Klicke auf **Publish release**.

## Schritt 5: In HACS testen

Da dein Repository nun öffentlich ist und ein Release hat, kann es jeder als "Custom Repository" in HACS hinzufügen.

1.  Öffne dein Home Assistant Dashboard.
2.  Gehe zu **HACS** > **Integrations**.
3.  Klicke oben rechts auf das Menü (drei Punkte) > **Custom repositories**.
4.  Füge die URL deines GitHub-Repositories ein.
5.  Kategorie: **Integration**.
6.  Klicke auf **Add**.

Wenn alles passt, wird deine Integration nun gelistet und kann installiert werden!

## Checkliste vor dem Upload

Stelle sicher, dass diese Dateien korrekt sind (bereits geprüft):
*   [x] `hacs.json` (Definiert den Namen und was gerendert wird)
*   [x] `custom_components/preheat/manifest.json` (Version `2.2.0` muss zum Git-Tag passen)
