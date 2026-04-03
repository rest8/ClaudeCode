"""Creates a Windows desktop shortcut for the iFOREX Trading Bot.

Run this script once after setup:
    python create_shortcut.py
"""

import os
import sys


def create_shortcut() -> None:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(project_dir, "venv", "Scripts", "pythonw.exe")
    launcher_script = os.path.join(project_dir, "launcher.py")
    icon_path = os.path.join(project_dir, "icon.ico")

    # Use pythonw.exe (no console window) if venv exists, else fallback
    if not os.path.exists(venv_python):
        venv_python = os.path.join(project_dir, "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    shortcut_path = os.path.join(desktop, "iFOREX 自動売買.lnk")

    # Use VBScript to create the shortcut (works on all Windows without extra deps)
    vbs_content = f'''Set WshShell = WScript.CreateObject("WScript.Shell")
Set shortcut = WshShell.CreateShortcut("{shortcut_path}")
shortcut.TargetPath = "{venv_python}"
shortcut.Arguments = """{launcher_script}"""
shortcut.WorkingDirectory = "{project_dir}"
shortcut.Description = "iFOREX 自動売買システム"
shortcut.WindowStyle = 1
'''

    if os.path.exists(icon_path):
        vbs_content += f'shortcut.IconLocation = "{icon_path}"\n'

    vbs_content += "shortcut.Save\n"

    vbs_path = os.path.join(project_dir, "_create_shortcut.vbs")
    with open(vbs_path, "w", encoding="utf-8") as f:
        f.write(vbs_content)

    os.system(f'cscript //nologo "{vbs_path}"')
    os.remove(vbs_path)

    print(f"ショートカットを作成しました: {shortcut_path}")
    print("デスクトップの「iFOREX 自動売買」アイコンをダブルクリックで起動できます。")


if __name__ == "__main__":
    create_shortcut()
