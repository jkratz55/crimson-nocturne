"""Regenerate every procedural asset: `python3 tools/asset_pipeline/build_all.py`."""
import audio
import environment
import equipment
import hero
import sprites_misc

if __name__ == "__main__":
    hero.build()
    sprites_misc.build()
    equipment.build()
    environment.build()
    audio.build()
    print("All assets generated.")
