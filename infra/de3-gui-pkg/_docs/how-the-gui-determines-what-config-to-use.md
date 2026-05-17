# Goal
- Document how the GUI determines what config to use

# Background
- Running ". ./set_env.sh" from the repo with the config to use
  will set _FRAMEWORK_PKG_DIR to the correct value.
- The GUI uses _STACK_DIR to know which infra tree to scan.
- Running "make" from the repo with the config to use
   will set _STACK_DIR to the correct value.

# How to run the GUI
- ```cd <repo to use with gui>```
- ``` . set_env.sh```
- ```./run -A de3-gui```
