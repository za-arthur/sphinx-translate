#!/usr/bin/env python
# -*- coding: utf-8 -*-
import aiohttp
import asyncio
import click
import io
import os
import urllib.parse

from concurrent.futures import ThreadPoolExecutor
from babel.messages import pofile

class YandexTranslateException(Exception):
    error_codes = {
        401: 'ERR_KEY_INVALID',
        402: 'ERR_KEY_BLOCKED',
        403: 'ERR_DAILY_REQ_LIMIT_EXCEEDED',
        404: 'ERR_DAILY_CHAR_LIMIT_EXCEEDED',
        413: 'ERR_TEXT_TOO_LONG',
        422: 'ERR_UNPROCESSABLE_TEXT',
        501: 'ERR_LANG_NOT_SUPPORTED',
    }

    def __init__(self, status_code, message, *args, **kwargs):
        message = self.error_codes.get(status_code, str(status_code)) + ': ' + message
        super(YandexTranslateException, self).__init__(message, *args, **kwargs)

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

api_url = 'https://translate.yandex.net/api/{version}/tr.json/{endpoint}'
api_version = 'v1.5'

async def translate_entry(session, text, source_lang, target_lang, api_key):
    data = {
        'key': api_key,
        'text': urllib.parse.quote_plus(text),
        'lang': f'{source_lang}-{target_lang}'}
    async with session.post(api_url.format(version=api_version, endpoint='translate'),
        data=data) as response:
        result = await response.json()
        print(data['lang'], result)
        if result['code'] != 200:
            raise YandexTranslateException(result['code'], result.get('message'))

        return urllib.parse.unquote_plus(result['text'][0])

async def translate(locale_dir, source_language, target_languages,
    api_key, line_width):
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor() as executor:
        async with aiohttp.ClientSession() as session:
            for lang in target_languages:
                po_dir = os.path.join(locale_dir, lang, 'LC_MESSAGES')

                for dirpath, dirnames, filenames in os.walk(po_dir):
                    for filename in filenames:
                        po_file = os.path.join(dirpath, filename)
                        base, ext = os.path.splitext(po_file)
                        if ext != ".po":
                            continue

                        cat_po = await loop.run_in_executor(executor, load_po, po_file)
                        need_write = False

                        for msg in cat_po:
                            # Skip already translated text
                            # if msg.string:
                                # continue
                            if not msg.id:
                                continue

                            msg.string = await translate_entry(session, msg.id,
                                source_language, lang, api_key)
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
                        return

    loop.close()

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
    '-k', '--api-key',
    envvar='YANDEX_API_KEY', metavar='<YANDEX_API_KEY>', required=True,
    help='Yandex API key')
@click.option(
    '-w', '--line-width',
    type=int, default=76, metavar='<WIDTH>', show_default=True, multiple=False,
    help='The maximum line width for the po files, 0 or a negative number '
         'disable line wrapping')
def main(config, source_language, target_language, api_key, line_width):
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
        translate(locale_dir, source_language, target_languages, api_key, line_width))

if __name__ == '__main__':
    main()
