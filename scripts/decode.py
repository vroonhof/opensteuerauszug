import sys
import argparse
from PIL import Image
from pdf417decoder import PDF417Decoder
import zlib
import os
import fitz  # PyMuPDF
import traceback

def decode_barcode(image, context=""):
    """
    Decodes PDF417 barcodes from a given image.

    Args:
        image (Image.Image): A PIL Image object.
        context (str, optional): Context information (e.g., page number, filename). Defaults to "".

    Returns:
        list: A list of decoded barcode information.  Returns an empty list if no barcodes are found.
    """
    decoder = PDF417Decoder(image)
    num_barcodes = decoder.decode()
    if num_barcodes > 0:
        print(f"Decoded {num_barcodes} barcode(s) from {context}")
        return decoder.barcodes_info
    else:
        print(f"No barcodes found in {context}")
        return [] # Return empty list if no barcodes are found.

def write_file(data, file_name):
    """
    Writes data to a file.

    Args:
        data (bytes): The data to write.
        file_name (str): The name of the file to write to.
    """
    try:
        with open(file_name, "wb") as f:
            f.write(data)
        print(f"Successfully wrote data to {file_name}")
    except Exception as e:
        print(f"Error writing to file {file_name}: {e}")

def process_output(info_list, output_file, decode_zlib=True):
    """
    Processes the decoded barcode information, assembles the data,
    decompresses it (optionally), and writes it to the output file.

    Args:
        info_list (list): A list of barcode information objects.
        output_file (str): The path to the output file.
        decode_zlib (bool, optional):  If True, performs zlib decompression. Defaults to True.
    """
    if not info_list:
        print("No barcodes found in any of the input images.")
        sys.exit(1)

    try:
        assembled_data = PDF417Decoder.assemble_data(info_list)
        print(f"Decompressing {decode_zlib}")
        if decode_zlib:
            decompressed_data = zlib.decompress(assembled_data)  # Decompress the data
            write_file(decompressed_data, output_file)
        else:
            write_file(assembled_data, output_file)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except zlib.error as e:
        print(f"Error: Decompression error: {e}")
        sys.exit(1)

def process_pdf(pdf_path, output_file, verbose=False, decode_zlib=True):
    """
    Processes a PDF file, rendering each page as an image and decoding barcodes.

    Args:
        pdf_path (str): Path to the PDF file.
        output_file (str): Path to the output file.
        verbose (bool): If True, print detailed error information (traceback).
    """
    try:
        pdf_document = fitz.open(pdf_path)
        info_list = []
        for page_number in range(pdf_document.page_count):
            page = pdf_document.load_page(page_number)  # Load each page
            pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # Get pixel map of the page at 300 dpi
            try:
                # Convert to a PIL-compatible format.
                if pix.colorspace.n == 1:
                    image_mode = "L"  # Grayscale
                elif pix.colorspace.n == 3:
                    image_mode = "RGB"  # RGB
                elif pix.colorspace.n == 4:
                    image_mode = "CMYK"  # CMYK
                else:
                    raise ValueError(f"Unsupported colorspace: {pix.colorspace}")
                img_bytes = pix.samples
                pil_image = Image.frombytes(image_mode, [pix.width, pix.height], img_bytes)
            except Exception as e:
                print(f"Error during image processing: {e}")
                if verbose:
                    traceback.print_exc()
                sys.exit(1)

            print(f"Image width: {pix.width}, height: {pix.height}")
            print(f"Image format: {image_mode}")

            # Save the image temporarily (optional, but helpful for debugging)
            # temp_image_path = f"temp_page_{page_number + 1}.png"
            # pil_image.save(temp_image_path)
            # Decode the barcode from the temporary image
            decoded_info = decode_barcode(pil_image, context=f"page {page_number + 1} of {pdf_path}") # Pass the page number and pdf_path
            if decoded_info:
                info_list.extend(decoded_info)
            # if os.path.exists(temp_image_path):  # Clean up the temporary image
            #     os.remove(temp_image_path)
        pdf_document.close()
        process_output(info_list, output_file, decode_zlib)

    except Exception as e:
        print(f"Error processing PDF: {e}")
        if verbose:
            traceback.print_exc()  # Print the traceback
        sys.exit(1)

def process_images(image_files):
    """
    Processes a list of image files, decoding barcodes from each.

    Args:
        image_files (list): A list of paths to image files.

    Returns:
        list: A list of barcode information objects.
    """
    info_list = []
    for file_path in image_files:
        try: #added try and except
            image = Image.open(file_path) # open image
            decoded_info = decode_barcode(image, context=file_path)  # Pass the file path as context, and the image object
            if decoded_info:
                info_list.extend(decoded_info)
        except Exception as e:
            print(f"Error processing image {file_path}: {e}") #error message
    return info_list

def main():
    """
    Main function to parse command line arguments, decode barcodes,
    assemble data, and write to a file.
    """
    parser = argparse.ArgumentParser(description="Decode PDF417 barcodes from images and save the data.")
    parser.add_argument("files", nargs='+', help="Paths to the barcode image files or a single PDF file.")
    parser.add_argument("-o", "--output", help="Path to the output file. Defaults to the first image/PDF file name with .xml extension.", default=None)
    parser.add_argument("-v", "--verbose", action='store_true', help="Enable verbose output, including tracebacks for PDF processing errors.")
    parser.add_argument("-z", "--zlib", action='store_true', help="Zlib decompression.", default=False)


    args = parser.parse_args()
    files = args.files
    output_file = args.output
    verbose = args.verbose # Get the value of the verbose argument
    decode_zlib = args.zlib

    if not output_file:
        # Default output file name
        base_name = os.path.splitext(os.path.basename(files[0]))[0]
        output_file = base_name + ".xml"

    if len(files) == 1 and files[0].lower().endswith(".pdf"):
        process_pdf(files[0], output_file, verbose, decode_zlib) 
    else:
        info_list = process_images(files) # Call process_images to handle image files
        process_output(info_list, output_file, decode_zlib) # Pass the zlib flag
        

if __name__ == "__main__":
    main()
