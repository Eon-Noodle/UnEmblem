# -*- mode: python -*-
import sys, os

block_cipher = None
name = 'unemblem'
project = name + '.ltproj'


a = Analysis(['run_engine.py'],
             pathex=['.'],
             binaries=[],
             datas=[('saves/save_storage.txt', 'saves'),
                    ('resources', 'resources'),
                    ('sprites', 'sprites'),
                    (project, os.path.basename(project)),
                    ('favicon.ico', '.'),
                    ('app', 'app')],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name=name,
          debug=False,
          strip=False,
          upx=True,
          console=True,
          icon='favicon.ico',
          contents_directory='.' )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name=name)
