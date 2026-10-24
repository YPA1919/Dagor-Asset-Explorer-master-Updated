"""Decode asset identifiers consistently across model and skeleton streams."""
import logging

def decode_asset_name(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        # Older authoring assets contain Windows-1251 identifiers. Use the same
        # strict fallback on both sides of skeleton/model name matching.
        name = data.decode('cp1251')
        logging.getLogger(__name__).debug('Legacy Windows-1251 asset name: %r', name)
        return name
