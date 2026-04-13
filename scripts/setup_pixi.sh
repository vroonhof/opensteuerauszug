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
    echo "Operating system not supported. Setup not possible."
    return 1 # exit will kill bash after sourcing, use return
else
  printf -- "--> pixi found.\n\n"
fi

# check if pixi workspace exists
if ! pixi info | grep -q "Name: $PIXI_ENV_NAME"; then
  # create pixi workspace 
  printf -- "--> pixi environment '$PIXI_ENV_NAME' not found\n"
  printf -- "--> Creating new pixi workspace: $PIXI_ENV_NAME\n"
  pixi init
  pixi add --pypi --editable "$PIXI_ENV_NAME @ file:$PWD"
  printf -- "--> framework added\n"
else
  printf --  "--> pixi workspace $PIXI_ENV_NAME found\n\n"
fi
# activate pixi 

if [ $# -eq 0 ]; then 
  printf -- "--> Activating pixi dev environment\n"
  pixi shell -e dev
elif [ "$1" == "-b" ]; then
  printf -- "--> Not Activating pixi environment\n"
else
  printf -- "--> Activating pixi dev environment\n"
  pixi shell -e dev
fi
