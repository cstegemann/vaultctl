# vaultctl
A simple python cli tool to "split" my notes into different vaults for easier management, more of a hobby project.

> this is in parts specific to my setup, e.g. ubuntu, using obsidian as a default viewer etc. Change config as needed, but beware that this is a very brittle hobby project

## Installation

> make sure to copy config.toml to your config path (-> your path/.config/vaultctl/config.toml) and adjust as needed

I'm using pipx to make the script available via command line. With pipx, simply run
```
cd LOCATION_OF_THIS_REPO
pipx install .
```
where the location is the top level of this repo, where the pyproject.toml lives

to upgrade after pulling / editing:

```
cd LOCATION_OF_THIS_REPO
pipx upgrade vaultctl
```

uninstall with:
```
pipx uninstall vaultctl
```
