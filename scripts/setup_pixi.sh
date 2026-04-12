#!/bin/bash
# define conda environment name
PIXI_ENV_NAME=opensteuerauszug

# check if the pixi command exists
PIXI_INSTALLED=false
if command -v pixi &> /dev/null; then
  PIXI_INSTALLED=true
fi

# check if pixi is already installed
if [[ "$PIXI_INSTALLED" = false ]]; then
  printf "No installed pixi found!\n"
  printf -- "--> Installing pixi ..\n\n"
  # installation for macOS or linux 
  if [[ $OSTYPE == 'darwin'* || $OSTYPE == 'linux'* ]]; then
    curl -fsSL https://pixi.sh/install.sh | sh
    if [ -n "$BASH_VERSION" ]; then
      printf -- "--> sourcing ~/.bashrc\n\n"
      source ~/.bashrc
    elif [ -n "$ZSH_VERSION" ]; then
      printf -- "--> sourcing ~/.zshrc\n\n"
      source ~/.zshrc
    elif [ -n "$tcsh" ] || [ -n "$csh" ]; then
      printf -- "--> sourcing ~/.cshrc\n\n"
      source ~/.cshrc
    fi
  # installation for linux
  # other operating system not supported
  else
    echo "Operating system not supported. Setup not possible."
    return 1 # exit will kill bash after sourcing, use return
  fi
else
  printf -- "--> pixi found.\n\n"
fi

# check if pixi workspace exists
if ! pixi info | grep -q "Name: $PIXI_ENV_NAME"; then
  # create pixi workspace 
  printf -- "--> pixi environment '$PIXI_ENV_NAME' not found\n"
  printf -- "--> Creating new pixi workspace: $PIXI_ENV_NAME\n"
  pixi init -i requirements.yaml
  printf -- "--> adding framework as pypi package\n"
  pixi add --pypi --editable "$PIXI_ENV_NAME @ file:$PWD"
  printf -- "--> framework added\n"
else
  printf --  "--> pixi workspace $PIXI_ENV_NAME found\n\n"
fi
# activate pixi 

if [ $# -eq 0 ]; then 
  printf -- "--> Activating pixi environment\n"
  pixi shell
elif [ "$1" == "-b" ]; then
  printf -- "--> Not Activating pixi environment\n"
else
  printf -- "--> Activating pixi environment\n"
  pixi shell
fi
