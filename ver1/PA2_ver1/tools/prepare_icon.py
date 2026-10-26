"""Convert the approved PNG into a multi-resolution Windows icon."""
import argparse
import shutil
from pathlib import Path
from PIL import Image

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('input',type=Path); args=parser.parse_args()
    target=Path(__file__).resolve().parents[1]/'assets'
    shutil.copyfile(args.input,target/'pa2_icon.png')
    with Image.open(args.input) as image:
        image.save(target/'pa2_icon.ico',format='ICO',sizes=[(n,n) for n in (16,24,32,48,64,128,256)])

if __name__=='__main__':main()
