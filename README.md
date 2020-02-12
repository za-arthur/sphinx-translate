# sphinx-tr - translate Sphinx .po files

## Installation

Before running the script you should ensure that you have already installed
Python 3, additionally you should install the requirements.

It is better to initialize a virtual environment. Run the following:

```
python -m venv env
source env/bin/activate
```

And then install the requirements for the environment:

```
pip install -r requirements.txt
```

## Usage

The `sphinx-tr` has the following command line options:

- `-c` or `--config` - Sphinx conf.py file to read a locale directory setting. By
  default it is `source/conf.py` within the current directory.
- `--source-language` - Source language to update po files.
- `--target-language` - Target language to update po files.
- `-w` or `--line-width` - The maximum line width for the po files, 0 or a negative
  number disable line wrapping. By default it is 76.

For example to translate .po files from Japanese to English you need to run the
following command:

```
./sphinx-tr.py --source-language ja --target-language en --config <path-to-doc>/source/config.py
```
