import functools
import subprocess
import os

import sublime


def merlin_bin():
    """
    Return the path of the ocamlmerlin binary."
    """

    user_settings = sublime.load_settings("Merlin.sublime-settings")
    merlin_path = user_settings.get('ocamlmerlin_path')
    if merlin_path:
        return merlin_path

    # For Mac OS X, add the path for homebrew
    if "/usr/local/bin" not in os.environ['PATH'].split(os.pathsep):
        os.environ['PATH'] += os.pathsep + "/usr/local/bin"
    opam_process = subprocess.Popen('opam config var bin', stdout=subprocess.PIPE, shell=True)
    opam_bin_path = opam_process.stdout.read().decode('utf-8').rstrip() + '/ocamlmerlin'

    if os.path.isfile(opam_bin_path) and os.access(opam_bin_path, os.X_OK):
        return opam_bin_path
    else:
        return 'ocamlmerlin'


def is_ocaml(view):
    """
    Check if the current view is an OCaml source code.
    """

    matcher = 'source.ocaml'
    location = view.sel()[0].begin()
    return view.match_selector(location, matcher)


def only_ocaml(func):
    """
    Execute the given function if we are in an OCaml source code only.
    """

    @functools.wraps(func)
    def wrapper(self, view, *args, **kwargs):
        if is_ocaml(view):
            return func(self, view, *args, **kwargs)

    return wrapper


def merlin_pos(view, pos):
    """
    Convert a position returned by Merlin to a Sublime text point.
    Sublime uses character positions and starts each file at line 0.
    """

    return view.text_point(pos['line'] - 1, pos['col'])


def clean_whitespace(text):
    """
    Replace sequence of whitespaces by a single space
    """

    return ' '.join(text.split())
