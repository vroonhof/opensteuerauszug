#!/bin/bash

# Check if exactly two arguments (source and destination directories) are provided
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <source_directory> <destination_directory>"
  echo "Example: $0 /home/user/my_xsd_files /home/user/converted_txt_files"
  exit 1
fi

# Assign arguments to variables
SOURCE_DIR="$1"
DEST_DIR="$2"

# Check if the source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
  echo "Error: Source directory '$SOURCE_DIR' does not exist."
  exit 1
fi

# Create the destination directory if it doesn't exist
mkdir -p "$DEST_DIR"

# Loop through all .xsd files in the source directory
for file in "$SOURCE_DIR"/*.xsd; do
  # Check if any .xsd files were found
  if [ -e "$file" ]; then # -e checks if a file exists (to handle cases where no .xsd files are found)
    # Get the filename without the path
    filename=$(basename "$file")

    # Remove the .xsd extension and add .txt
    new_filename="${filename%.xsd}.txt"

    # Copy the file to the destination directory with the new name
    cp "$file" "$DEST_DIR/$new_filename"
    echo "Copied '$file' to '$DEST_DIR/$new_filename'"
  else
    echo "No .xsd files found in '$SOURCE_DIR'."
    break # Exit the loop if no files were found
  fi
done

echo "Copy process complete!"
