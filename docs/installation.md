# 📦 Installation Guide

## Option 1: HACS (Recommended)

The easiest way to install **Intelligent Preheating** is via HACS (Home Assistant Community Store).

1.  Open **HACS** in your Home Assistant sidebar.
2.  Click on **Integrations**.
3.  Click the **3 dots** (top right) → **Custom repositories**.
4.  Add `https://github.com/Ecronika/ha-preheat` as repository URL.
5.  Select **Integration** as category.
6.  Click **Add**.
7.  Search for **"Intelligent Preheating"** (if not already visible).
8.  Click **Download**.
9.  **Restart Home Assistant**.

## Option 2: Manual Installation

If you do not use HACS, you can install the component manually.

1.  Download the latest release zip from the [Releases Page](https://github.com/Ecronika/ha-preheat/releases).
2.  Unzip the file.
3.  Copy the folder `custom_components/preheat` into your Home Assistant configuration directory's `custom_components/` folder.
    *   Target path: `/config/custom_components/preheat/`
4.  **Restart Home Assistant**.

## Post-Installation Setup

After restarting, you must add the integration to Home Assistant:

1.  Go to **Settings** → **Devices & Services**.
2.  Click **+ ADD INTEGRATION** (bottom right).
3.  Search for **"Intelligent Preheating"**.
4.  Click on the entry to start the configuration wizard.
