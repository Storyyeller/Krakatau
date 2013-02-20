import os.path, zipfile

def findFiles(target, recursive, prefix):
    if target.endswith('.jar'):
        with zipfile.ZipFile(target, 'r') as archive:
            targets = [name for name in archive.namelist() if name.endswith(prefix)]
    else:
        if recursive:
            assert(os.path.isdir(target))
            targets = []

            for root, dirs, files in os.walk(target):
                targets += [os.path.join(root, fname) for fname in files if fname.endswith(prefix)]
        else:
            return [target]
    return targets

def normalizeClassname(name):
    if name.endswith('.class'):
        name = name[:-6]
    # Replacing backslashes is ugly since they can be in valid classnames too, but this seems the best option
    return name.replace('\\','/').replace('.','/')

def writeFile(base_path, name, suffix, data):
    out = base_path      
    if os.path.isdir(out):
        out = os.path.join(out, *name.split('/'))
        out += suffix

    dirpath = os.path.dirname(out)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath)

    with open(out,'wb') as f:
        f.write(data)
    return out