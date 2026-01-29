import os

import easyocr

def main():
    print("OCR Translator")
    reader = easyocr.Reader(['en'], gpu=False)

if __name__ == "__main__":
    main()
