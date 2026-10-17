"""Create an isolated Fontconfig profile for legitimately installed font files.

Does not download or redistribute fonts and does not modify system configuration.
Example: python scripts/configure_fonts024.py /path/to/fonts --output artifacts/fonts
Run workers with FONTCONFIG_FILE pointing at the resulting fonts.conf.
"""
import argparse
from pathlib import Path
from xml.sax.saxutils import escape


def configure(fonts: Path, destination: Path):
    fonts=fonts.expanduser().resolve()
    if not fonts.is_dir() or not any(p.suffix.lower() in {'.ttf','.otf','.ttc'} for p in fonts.rglob('*')):
        raise ValueError('No font files in the supplied directory')
    destination=destination.expanduser().resolve();destination.mkdir(parents=True,exist_ok=False)
    cache=destination/'cache';cache.mkdir()
    config=destination/'fonts.conf'
    config.write_text('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
        '<fontconfig><include>/etc/fonts/fonts.conf</include><dir>'+escape(str(fonts))+'</dir>'
        '<cachedir>'+escape(str(cache))+'</cachedir></fontconfig>\n')
    return config

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('fonts',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    print(configure(args.fonts,args.output))
