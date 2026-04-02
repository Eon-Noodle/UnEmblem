import os
from pathlib import Path

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
IGNORE_FOLDERS = {'.git', '__pycache__'}
START_PATH = Path('.').resolve()

# Marker to identify auto-generated galleries
GALLERY_MARKER = "<!-- AUTO-GENERATED-IMAGE-GALLERY -->"

def is_auto_generated_gallery(readme_path):
    if not readme_path.exists():
        return False
    
    try:
        content = readme_path.read_text(encoding='utf-8')
        return GALLERY_MARKER in content
    except:
        return False

def generate_folder_readme(folder_path, images):
    readme_path = Path(folder_path) / "README.md"
    
    content = GALLERY_MARKER + \
                '\n'.join('![%s](%s)' % (img_path.name, img_path.relative_to(folder_path)) \
                            for img_path in images)  
    readme_path.write_text(content, encoding='utf-8')

def scan_and_generate():
    for root, dirs, files in os.walk(START_PATH):
        dirs[:] = [d for d in dirs if d not in IGNORE_FOLDERS]       
        root_path = Path(root)

        need_update = False
        readme_path = root_path / "README.md"
        if readme_path.exists():
            if is_auto_generated_gallery(readme_path):
                need_update = True
            else:
                continue

        images = []
        for file in files:
            if Path(file).suffix in IMAGE_EXTENSIONS:
                images.append(root_path / file)
        
        if images:
            images.sort()
            generate_folder_readme(root_path, images)

        elif need_update:
            readme_path.unlink()

if __name__ == "__main__":
    scan_and_generate()