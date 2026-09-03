"""Place number anchors outside the target and any overlapping neighbouring region."""


def number_anchor(region, regions, image_height):
    x,y,_,_=region['bbox']
    for _ in regions:
        blockers=[other['bbox'][0] for other in regions if other['id'] != region['id']
                  and other['bbox'][1] <= y + .025*image_height
                  and other['bbox'][3] >= y - .01*image_height
                  and other['bbox'][0] < x <= other['bbox'][2]]
        if not blockers:
            break
        x=min(blockers)
    return x,y
