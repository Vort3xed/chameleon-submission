"""Catalogue of real-world canvas formats ("fixed materials" per RULES.md).

Scoring targets are drawn from formats like these; the hidden ones will be
unseen, so the test set samples broadly across aspect ratios and sizes.
"""

FORMATS = [
    # name, width, height
    ("Instagram Post", 1080, 1080),
    ("Instagram Portrait", 1080, 1350),
    ("Instagram Story", 1080, 1920),
    ("Instagram Landscape", 1080, 566),
    ("Facebook Post", 1200, 630),
    ("Facebook Cover", 820, 312),
    ("Facebook Event Cover", 1920, 1005),
    ("X Post", 1600, 900),
    ("X Header", 1500, 500),
    ("LinkedIn Post", 1200, 627),
    ("LinkedIn Banner", 1584, 396),
    ("YouTube Thumbnail", 1280, 720),
    ("YouTube Channel Art", 2560, 1440),
    ("Pinterest Pin", 1000, 1500),
    ("Pinterest Long Pin", 1000, 2100),
    ("TikTok Video Cover", 1080, 1920),
    ("Snapchat Ad", 1080, 1920),
    ("Web Leaderboard", 728, 90),
    ("Super Leaderboard", 970, 90),
    ("Billboard Ad", 970, 250),
    ("Medium Rectangle", 300, 250),
    ("Large Rectangle", 336, 280),
    ("Square Ad", 250, 250),
    ("Wide Skyscraper", 160, 600),
    ("Half Page Ad", 300, 600),
    ("Mobile Banner", 320, 50),
    ("Large Mobile Banner", 320, 100),
    ("Presentation 16:9", 1920, 1080),
    ("Presentation 4:3", 1024, 768),
    ("Poster 18x24", 1800, 2400),
    ("A4 Portrait", 2480, 3508),
    ("A4 Landscape", 3508, 2480),
    ("US Letter Flyer", 1275, 1650),
    ("Email Header", 600, 200),
    ("Twitch Banner", 1200, 480),
    ("Etsy Shop Banner", 3360, 840),
    ("Desktop Wallpaper", 2560, 1440),
    ("Phone Wallpaper", 1170, 2532),
    ("Business Card", 1050, 600),
    ("Postcard", 1800, 1200),
    ("Google Display Square", 1200, 1200),
    ("Spotify Canvas", 720, 1280),
]

# Formats that commonly appear as *source* designs.
SOURCE_FORMATS = [
    ("Instagram Post", 1080, 1080),
    ("Instagram Portrait", 1080, 1350),
    ("Instagram Story", 1080, 1920),
    ("Facebook Post", 1200, 630),
    ("Presentation 16:9", 1920, 1080),
    ("Pinterest Pin", 1000, 1500),
    ("X Post", 1600, 900),
    ("Poster 18x24", 1800, 2400),
    ("YouTube Thumbnail", 1280, 720),
    ("Google Display Square", 1200, 1200),
    ("US Letter Flyer", 1275, 1650),
    ("X Header", 1500, 500),
]


def ratio_distance(w1, h1, w2, h2):
    """How different two aspect ratios are: |log(ar1/ar2)| (0 = same shape)."""
    import math

    return abs(math.log((w1 / h1) / (w2 / h2)))
