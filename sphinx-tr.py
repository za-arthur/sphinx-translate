#!/usr/bin/env python
# -*- coding: utf-8 -*-
import aiohttp
import asyncio
import click
import io
import random
import os
import urllib.parse

from babel.messages import pofile
from concurrent.futures import ThreadPoolExecutor
from lxml import html

class SphinxTranslateException(Exception):
    def __init__(self, status_code, message, *args, **kwargs):
        message = str(status_code) + ': ' + message
        super(SphinxTranslateException, self).__init__(message, *args, **kwargs)

def read_config(path):
    namespace = {
        '__file__': os.path.abspath(path),
    }

    olddir = os.getcwd()
    try:
        if not os.path.isfile(path):
            msg = "'%s' is not found." % path
            raise click.BadParameter(msg)
        os.chdir(os.path.dirname(path) or ".")

        filepath = os.path.basename(path)
        with open(filepath, 'rb') as f:
            source = f.read()

        code = compile(source, filepath, 'exec')
        exec(code, namespace)
    finally:
        os.chdir(olddir)

    return namespace

def load_po(filename):
    with io.open(filename, 'rb') as f:
        cat = pofile.read_po(f)
    charset = cat.charset or 'utf-8'

    with io.open(filename, 'rb') as f:
        return pofile.read_po(f, charset=charset)

def dump_po(filename, catalog, line_width=76):
    dirname = os.path.dirname(filename)
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    # Because babel automatically encode strings, file should be open as binary mode.
    with io.open(filename, 'wb') as f:
        pofile.write_po(f, catalog, line_width)

# ==================================
# translation

def parse_translated_entry(text, filename):
    doc = html.fromstring(text)

    item = doc.xpath("//div[@class='t0' and @dir='ltr']//text()")
    if not item:
        return ""
    # Replace extra ' + ' entries
    return (item[-1].replace(' + ', ' ')
        .replace('C #', 'C#')
        .replace('C ++', 'C++')
        .replace('+-+', '-')
        .replace(' :: ', '::')
        .replace('! =', '!=')
        .replace('> =', '>=')
        .replace(' +', '')
        .replace(' / ', '/')
        .replace('../ ', '../')
        .replace(' // ', '//')
        .replace(': doc: `', ':doc:`')
        .replace(': ref: `', ':ref:`')
        .replace('` _', '`_'))

api_url = 'https://translate.google.pl/m'

async def translate_entry(session, text, source_lang, target_lang, filename):
    params = {
        'hl': source_lang,
        'sl': source_lang,
        'tl': target_lang,
        'ie': 'UTF-8',
        'prev': '_m',
        'q': text
    }

    # Sleep random milliseconds
    delay = random.randint(100, 1000) / 1000
    await asyncio.sleep(delay)

    async with session.get(api_url, params=params) as response:
        if response.status != 200:
            raise SphinxTranslateException(response.status, response.reason)

        result = await response.text()
        return result

async def get_po_files(locale_dir, languages, q):
    for lang in languages:
        po_dir = os.path.join(locale_dir, lang, 'LC_MESSAGES')

        for dirpath, dirnames, filenames in os.walk(po_dir):
            for filename in filenames:
                po_file = os.path.join(dirpath, filename)
                base, ext = os.path.splitext(po_file)

                if ext == ".po":
                    await q.put((lang, po_file))

async def translate_files(source_language, line_width, loop, executor, session, q):
    while True:
        target_language, po_file = await q.get()

        cat_po = await loop.run_in_executor(executor, load_po, po_file)
        need_write = False

        for msg in cat_po:
            # Skip messages with already translated text or
            # with empty source string
            if msg.string or not msg.id:
                continue

            translate_result = await translate_entry(session, msg.id,
                source_language, target_language, po_file)
            msg.string = await loop.run_in_executor(executor,
                parse_translated_entry, translate_result, po_file)

            need_write = True

        if need_write:
            click.echo('Update: {0}'.format(po_file))
            po_file_tmp = po_file + ".tmp"

            try:
                await loop.run_in_executor(executor, dump_po,
                    po_file_tmp, cat_po, line_width)
                os.replace(po_file_tmp, po_file)
            except:
                os.remove(po_file_tmp)
                raise

        q.task_done()

async def translate(locale_dir, source_language, target_languages, line_width):
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor() as executor:
        headers = {
            'User-Agent': 'Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.0)'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            q = asyncio.Queue()
            producer = asyncio.create_task(get_po_files(locale_dir, target_languages, q))
            consumers = [asyncio.create_task(translate_files(source_language,
                line_width, loop, executor, session, q)) for _ in range(4)]

            await asyncio.gather(producer)
            await q.join()

            for c in consumers:
                c.cancel()

# ==================================
# click options

class LanguagesType(click.ParamType):
    name = 'languages'
    envvar_list_splitter = ','

    def convert(self, value, param, ctx):
        langs = value.split(',')
        return tuple(langs)

LANGUAGES = LanguagesType()

@click.command()
@click.option(
    '-c', '--config',
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    default=None, metavar='<FILE>',
    help='Sphinx conf.py file to read a locale directory setting.')
@click.option(
    '--source-language',
    metavar='<LANG>', required=True,
    help='Source language to update po files.')
@click.option(
    '--target-language',
    type=LANGUAGES, metavar='<LANG>', multiple=True, required=True,
    help='Target language to update po files.')
@click.option(
    '-w', '--line-width',
    type=int, default=76, metavar='<WIDTH>', show_default=True, multiple=False,
    help='The maximum line width for the po files, 0 or a negative number '
         'disable line wrapping')
def main(config, source_language, target_language, line_width):
    # load conf.py
    if config is None:
        for c in ('conf.py', 'source/conf.py'):
            if os.path.exists(c):
                config = c
                break
    # for locale_dir
    locale_dir = None
    if config:
        cfg = read_config(config)
        if 'locale_dirs' in cfg:
            locale_dir = os.path.join(
                os.path.dirname(config), cfg['locale_dirs'][0])
    # languages
    if not source_language:
        msg = ("No languages are found. Please specify language with --source-language option.")
        raise click.BadParameter(msg, param_hint='source-language')
    if not target_language:
        msg = ("No languages are found. Please specify language with --target-language option.")
        raise click.BadParameter(msg, param_hint='target-language')

    target_languages = sum(target_language, ())
    asyncio.run(
        translate(locale_dir, source_language, target_languages, line_width))

if __name__ == '__main__':
    main()
