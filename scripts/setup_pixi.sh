#!/bin/bash

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
if ! pixi info | grep -q "Name: opensteuerauszug"; then
  # create pixi workspace 
  printf -- "--> pixi workspace 'opensteuerauszug' not found\n"
  printf -- "--> Creating new pixi workspace: opensteuerauszug\n"
  pixi init --format pixi ../opensteuerauszug
  pixi add python
  pixi add --pypi --editable "opensteuerauszug[dev] @ file:$PWD"
  printf -- "--> workspace opensteuerauszug added\n"
else
  printf --  "--> pixi workspace opensteuerauszug found\n\n"
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
