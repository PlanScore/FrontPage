# Project Configuration

This is a Javascript project.

## Setup
- The code here is run by Docker using instructions from Quick Build in the README
- Don't try to run it yourself, let the user do it or tell the user how

## Git Configuration
- Always add individual files to git by name, never use general commands like "git add ." or "git add -A"
- This prevents unwanted files from being committed to the repository
- Always git add all touched files after making changes

## Selected Python Scripts
- Expect a working virtualenv in .venv, use it
- Scripts like update-ushouse-elections.py are used for special actions
- Prefer stdlib whenever possible, only use 3rd party packages when asked
- Use ruff check to lint Python code
