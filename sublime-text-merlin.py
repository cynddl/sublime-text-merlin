"""
This module allows you to analyse OCaml source code, autocomplete,
and infer types while writing.
"""

import functools
import sublime
import sublime_plugin
import re
import os
import sys
import html
import textwrap

if sys.version_info < (3, 0):
    from merlin.process import MerlinProcess, MerlinView
    from merlin.helpers import merlin_pos, only_ocaml, clean_whitespace
else:
    # Weird hacks to avoid sublime caching an old version
    if sys.version_info.minor < 4:
        from imp import reload
    else:
        from importlib import reload
    merlin_path = os.path.dirname(os.path.realpath(__file__))
    if merlin_path not in sys.path:
        sys.path.append(merlin_path)

    import merlin.process
    import merlin.helpers

    process = reload(merlin.process)
    helpers = reload(merlin.helpers)

    from merlin.process import MerlinProcess, MerlinView
    from merlin.helpers import merlin_pos, only_ocaml, clean_whitespace

running_process = None

enclosing = {}

phantom_style = """
<style>
    .merlin-phantom {
        color: var(--background);
        padding: 4px 8px;
        font-weight: bold;
    }

    .merlin-type {
        background-color: color(var(--bluish));
    }

    .merlin-warning {
        background-color: color(var(--orangish));
    }

    .merlin-error {
        background-color: color(var(--redish));
    }

    .merlin-type .counter {
        font-size: .8em;
        color: color(var(--background) blend(var(--bluish) 50%));
    }
</style>
"""

def merlin_process():
    global running_process
    if running_process is None:
        running_process = MerlinProcess()
    return running_process


def merlin_view(view):
    return MerlinView(merlin_process(), view)


class MerlinLoadPackage(sublime_plugin.WindowCommand):
    """
    Command to find packages and load them into the current view.
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.modules = self.merlin.find_list()
        self.window.show_quick_panel(self.modules, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.merlin.find_use(self.modules[index])


class MerlinAddBuildPath(sublime_plugin.WindowCommand):
    """
    Command to add a directory to the build path (for completion, typechecking, etc).
    """

    def run(self):
        view = self.window.active_view()
        file_name = view.file_name()
        self.merlin = merlin_view(view)

        if file_name:
            wd = os.path.dirname(os.path.abspath(file_name))
        else:
            wd = os.getcwd()

        self.window.show_input_panel("Add build path", wd, self.on_done, None, None)

    def on_done(self, directory):
        self.merlin.add_build_path(directory)


class MerlinAddSourcePath(sublime_plugin.WindowCommand):
    """
    Command to add a directory to the source path (for jumping to definition).
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)
        file_name = view.file_name()

        if file_name:
            wd = os.path.dirname(os.path.abspath(file_name))
        else:
            wd = os.getcwd()

        self.window.show_input_panel("Add source path", wd, self.on_done, None, None)

    def on_done(self, directory):
        self.merlin.add_source_path(directory)


class MerlinRemoveBuildPath(sublime_plugin.WindowCommand):
    """
    Command to remove a directory from the build path.
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.directories = self.merlin.list_build_path()
        self.window.show_quick_panel(self.directories, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.merlin.remove_build_path(self.directories[index])


class MerlinRemoveSourcePath(sublime_plugin.WindowCommand):
    """
    Command to remove a directory from the source path.
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.directories = self.merlin.list_source_path()
        self.window.show_quick_panel(self.directories, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.merlin.remove_source_path(self.directories[index])


class MerlinEnableExtension(sublime_plugin.WindowCommand):
    """
    Enable syntax extension
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.extensions = self.merlin.extension_list('disabled')
        self.window.show_quick_panel(self.extensions, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.merlin.extension_enable([self.extensions[index]])


class MerlinDisableExtension(sublime_plugin.WindowCommand):
    """
    Disable syntax extension
    """

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.extensions = self.merlin.extension_list('enabled')
        self.window.show_quick_panel(self.extensions, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.merlin.extension_disable([self.extensions[index]])

class MerlinTypeEnclosing:
    """
    Return type information around cursor.
    """

    def __init__(self, view):
        merlin = merlin_view(view)
        merlin.sync()

        # FIXME: proper integration into sublime-text
        # enclosing is a list of json objects of the form:
        # { 'type': string;
        #   'tail': "no"|"position"|"call" // tailcall information
        #   'start', 'end': {'line': int, 'col': int}
        # }
        self.view = view
        self.index = -1
        self.verbosity = 0
        self.merlin = merlin
        self.update_enclosing()

    def _item_region(self, item):
        start = merlin_pos(self.view, item['start'])
        end = merlin_pos(self.view, item['end'])
        return sublime.Region(start, end)

    def _item_format(self, item):
        text = item['type']
        if item['tail'] == 'position':
            text += " (*tail-position*)"
        if item['tail'] == 'call':
            text += " (*tail-call*)"
        return clean_whitespace(text)

    def _items(self):
        return list(map(self._item_format, self.enclosing))

    def show_region(self):
        enc = self.enclosing[self.index]

        start_text_point = self.view.text_point(enc["start"]["line"] - 1, enc["start"]["col"])
        end_text_point = self.view.text_point(enc["end"]["line"] - 1, enc["end"]["col"])

        self.view.add_regions("merlin_type_region", [ sublime.Region(start_text_point, end_text_point) ], "variable", "", sublime.DRAW_NO_FILL | sublime.DRAW_OUTLINED)

    def show_phantom(self):
        enc = self.enclosing[self.index]
        start_text_point = self.view.text_point(enc["start"]["line"] - 1, enc["start"]["col"])
        end_text_point = self.view.text_point(enc["end"]["line"] - 1, enc["end"]["col"])

        phantom_content = phantom_style + "<span class='merlin-phantom merlin-type'>: " + self._items()[self.index] + " <span class='counter'>(" + str(self.index + 1) + " of " + str(len(self.enclosing)) + ")</span></span>"
        self.view.add_phantom("merlin_type", sublime.Region(end_text_point, end_text_point), phantom_content, sublime.LAYOUT_INLINE)

    def show_popup(self):
        window = self.view.window()
        syntax_file = self.view.settings().get('syntax')
        sig_text = self.enclosing[self.index]["type"]

        enc = self.enclosing[self.index]
        start_text_point = self.view.text_point(enc["start"]["line"] - 1, enc["start"]["col"])
        end_text_point = self.view.text_point(enc["end"]["line"] - 1, enc["end"]["col"])

        phantom_content = phantom_style + "<span class='merlin-phantom merlin-type'>: <i>as output</i> <span class='counter'>(" + str(self.index + 1) + " of " + str(len(self.enclosing)) + ")</span></span>"
        self.view.add_phantom("merlin_type", sublime.Region(end_text_point, end_text_point), phantom_content, sublime.LAYOUT_INLINE)

        window.run_command("merlin_show_types_output", {"args": {"text": sig_text, "syntax": syntax_file}})

    def update_enclosing(self):
        pos = self.view.sel()
        line, col = self.view.rowcol(pos[0].begin())
        enclosing = self.merlin.type_enclosing(line + 1, col, verbosity=self.verbosity)
        self.enclosing = enclosing

    def show_deepen(self):
        self.update_enclosing()
        if self.index == -1:
            self.index = 0
        self.verbosity += 1
        self.show()

    def show_widen(self):
        if self.verbosity != 1:
            self.verbosity = 0
            self.update_enclosing()
            self.verbosity = 1
        self.index += 1
        self.index %= len(self.enclosing)
        self.show()

    def show(self):
        window = self.view.window()

        self.view.erase_phantoms("merlin_type")
        self.view.erase_regions("merlin_type_region")
        window.destroy_output_panel("merlin-types.mli")
        if len(self.enclosing) == 0:
            return

        if len(self.enclosing) <= self.index:
            return
        self.show_region()
        if "\n" not in self.enclosing[self.index]["type"]:
            self.show_phantom()
        else:
            self.show_popup()

    def show_menu(self):
        self.view.show_popup_menu(self._items(), self.on_done, sublime.MONOSPACE_FONT)

    def on_done(self, index):
        if index > -1:
            sel = self.view.sel()
            sel.clear()
            sel.add(self._item_region(self.enclosing[index]))

class MerlinTypeAtCursorCmd(sublime_plugin.WindowCommand):
    """
    Return type information around cursor.
    """

    def __init__(self, window):
        self.window = window

    def run(self):
        global enclosing

        view = self.window.active_view()
        id = view.id()
        if id not in enclosing or enclosing[id] == None:
            enclosing[id] = MerlinTypeEnclosing(view)

        enclosing[id].show_deepen()

class MerlinWidenTypeAtCursorCmd(sublime_plugin.WindowCommand):
    def __init__(self, window):
        self.window = window

    def run(self):
        global enclosing

        view = self.window.active_view()
        id = view.id()
        if id not in enclosing or enclosing[id] == None:
            enclosing[id] = MerlinTypeEnclosing(view)

        enclosing[id].show_widen()

class MerlinShowTypesOutput(sublime_plugin.TextCommand):
    def run(self, edit, args):
        sig_text = args["text"]
        syntax_file = args["syntax"]
        window = self.view.window()

        output = window.create_output_panel("merlin-types.mli")
        full_region = sublime.Region(0, output.size())
        output.replace(edit, full_region, sig_text)

        output.set_syntax_file(syntax_file)
        output.sel().clear()
        window.run_command("show_panel", {"panel": "output.merlin-types.mli"})



class MerlinTypeMenu(sublime_plugin.TextCommand):
    """
    Display type information in context menu
    """
    def run(self, edit):
        enclosing[self.view.id()] = MerlinTypeEnclosing(self.view)
        enclosing[self.view.id()].show_menu()


def merlin_locate_result(result, window):
    if isinstance(result, dict):
        pos = result['pos']
        if 'file' in result:
            filename = "%s:%d:%d" % (result['file'], pos['line'], pos['col'] + 1)
            window.open_file(filename, sublime.ENCODED_POSITION | sublime.TRANSIENT)
        else:
            view = window.active_view()
            sel = view.sel()
            sel.clear()
            pos = merlin_pos(view, pos)
            sel.add(sublime.Region(pos, pos))
            view.show_at_center(pos)
    else:
        sublime.message_dialog(result)


class MerlinLocateMli(sublime_plugin.WindowCommand):
    """
    Locate definition under cursor
    """
    def run(self):
        view = self.window.active_view()
        merlin = merlin_view(view)
        merlin.sync()

        pos = view.sel()
        line, col = view.rowcol(pos[0].begin())
        merlin_locate_result(merlin.locate(line + 1, col, kind=self.kind()), self.window)

    def kind(self):
        return "mli"


class MerlinLocateNameMli(sublime_plugin.WindowCommand):
    """
    Locate definition by name
    """
    def run(self, edit):
        self.window.show_input_panel("Enter name", "", self.on_done, None, None)

    def kind(self):
        return "mli"

    def on_done(self, name):
        view = self.window.active_view()
        merlin = merlin_view(view)
        merlin.sync()

        pos = view.sel()
        line, col = view.rowcol(pos[0].begin())
        merlin_locate_result(merlin.locate(line + 1, col, ident=name), self.window)


class MerlinLocateMl(MerlinLocateMli):
    def kind(self):
        return "ml"


class MerlinLocateNameMl(MerlinLocateNameMli):
    def kind(self):
        return "ml"


class MerlinWhich(sublime_plugin.WindowCommand):
    """
    Abstract command to quickly find a file.
    """

    def extensions(self):
        return []

    def run(self):
        view = self.window.active_view()
        self.merlin = merlin_view(view)

        self.files = self.merlin.which_with_ext(self.extensions())
        self.window.show_quick_panel(self.files, self.on_done)

    def on_done(self, index):
        if index != -1:
            module_name = self.files[index]
            modules = map(lambda ext: module_name + ext, self.extensions())
            self.window.open_file(self.merlin.which_path(list(modules)))


class MerlinFindMl(MerlinWhich):
    """
    Command to quickly find an ML file.
    """

    def extensions(self):
        return [".ml", ".mli"]


class MerlinFindMli(MerlinWhich):
    """
    Command to quickly find an MLI file.
    """

    def extensions(self):
        return [".mli", ".ml"]


class Autocomplete(sublime_plugin.EventListener):
    """
    Sublime Text autocompletion integration
    """

    completions = []
    cplns_ready = None

    @only_ocaml
    def on_query_completions(self, view, prefix, locations):
        """ Sublime autocomplete event handler. """

        # Expand the prefix with dots
        l = locations[0]
        line = view.substr(sublime.Region(view.line(l).a, l))

        try:
            prefix = re.findall(r"(([\w.]|->)+)", line)[-1][0]
        except IndexError:
            prefix = ""

        merlin = merlin_view(view)
        merlin.sync()

        default_return = ([], sublime.INHIBIT_WORD_COMPLETIONS)

        if self.cplns_ready:
            self.cplns_ready = None
            if self.completions:
                cplns, self.completions = self.completions, []
                return cplns

            return default_return

        if self.cplns_ready is None:
            self.cplns_ready = False
            line, col = view.rowcol(locations[0])
            result = merlin.complete_cursor(prefix, line + 1, col)

            self.cplns = []
            for r in result['entries']:
                name = clean_whitespace(r['name'])
                desc = clean_whitespace(r['desc'])
                self.cplns.append(((name + '\t' + desc), name))

            self.show_completions(view, self.cplns)

        return default_return

    @only_ocaml
    def show_completions(self, view, completions):
        self.cplns_ready = True
        if completions:
            self.completions = completions
            view.run_command("hide_auto_complete")
            sublime.set_timeout(functools.partial(self.show, view), 0)

    @only_ocaml
    def show(self, view):
        view.run_command("auto_complete", {
            'disable_auto_insert': True,
            'api_completions_only': True,
            'next_completion_if_showing': False,
            'auto_complete_commit_on_tab': True,
        })


# Error panel stuff derived from SublimeClang under zlib license;
# see https://github.com/quarnster/SublimeClang#license.
class MerlinErrorPanelFlush(sublime_plugin.TextCommand):
    def run(self, edit, data):
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, data)


class MerlinErrorPanel(object):
    def __init__(self):
        self.view = None
        self.data = ""

    def set_data(self, data):
        self.data = data
        if self.is_visible():
            self.flush()

    def is_visible(self, window=None):
        ret = (self.view is not None) and (self.view.window() is not None)
        if ret and window:
            ret = self.view.window().id() == window.id()
        return ret

    def flush(self):
        self.view.set_read_only(False)
        self.view.set_scratch(True)
        self.view.run_command("merlin_error_panel_flush", {"data": self.data})
        self.view.set_read_only(True)

    def open(self, window=None):
        if window is None:
            window = sublime.active_window()
        if not self.is_visible(window):
            self.view = window.get_output_panel("merlin")
            self.view.settings().set("result_file_regex", "^(.+):([0-9]+):([0-9]+)")
        self.flush()

        window.run_command("show_panel", {"panel": "output.merlin"})

    def close(self):
        sublime.active_window().run_command("hide_panel", {
            "panel": "output.merlin"
        })

merlin_error_panel = MerlinErrorPanel()


class MerlinBuffer(sublime_plugin.EventListener):
    """
    Synchronize the current buffer with Merlin and:
     - autocomplete words with type informations;
     - display errors in the gutter.
    """

    error_messages = []

    @only_ocaml
    def on_post_save(self, view):
        """
        Sync the buffer with Merlin on each text edit.
        """

        merlin_view(view).sync()
        self.display_errors(view)
        self.show_errors(view)

    @only_ocaml
    def on_modified(self, view):
        global enclosing
        view.erase_regions('ocaml-underlines-errors')
        view.erase_regions('ocaml-underlines-warnings')
        view.erase_regions("merlin_type_region")
        view.erase_phantoms("merlin_type")
        enclosing[view.id()] = None
        error_messages = []

    def _plugin_dir(self):
        path = os.path.realpath(__file__)
        root = os.path.split(os.path.dirname(path))[1]
        return os.path.splitext(root)[0]

    def gutter_icon_path(self):
        try:
            resource = sublime.load_binary_resource("gutter-icon.png")
            cache_path = os.path.join(sublime.cache_path(), "Merlin",
                                      "gutter-icon.png")

            if not os.path.isfile(cache_path):
                if not os.path.isdir(os.path.dirname(cache_path)):
                    os.makedirs(os.path.dirname(cache_path))
                with open(cache_path, "wb") as f:
                    f.write(resource)

            return "Cache/Merlin/gutter-icon.png"

        except IOError:
            return "Packages/" + self._plugin_dir() + "/gutter-icon.png"

    def show_errors(self, view):
        """
        Show a simple gutter icon for each parsing error.
        """

        view.erase_regions('ocaml-underlines-errors')
        view.erase_regions('ocaml-underlines-warnings')

        errors = merlin_view(view).report_errors()

        error_messages = []
        warning_underlines = []
        error_underlines = []

        for e in errors:
            if 'start' in e and 'end' in e:
                pos_start = e['start']
                pos_stop = e['end']
                pnt_start = merlin_pos(view, pos_start)
                pnt_stop = merlin_pos(view, pos_stop)
                r = sublime.Region(pnt_start, pnt_stop)

                message = e['message']

                if message[:7] == "Warning":
                    warning_underlines.append(r)
                else:
                    error_underlines.append(r)

                error_messages.append((r, message))


        view.add_regions('ocaml-underlines-warnings', warning_underlines, 'invalid.broken.ocaml', "dot", sublime.DRAW_NO_FILL | sublime.DRAW_OUTLINED)
        view.add_regions('ocaml-underlines-errors', error_underlines, 'invalid.illegal.ocaml', "dot", sublime.DRAW_NO_FILL | sublime.DRAW_OUTLINED)

        self.error_messages = error_messages
        # add_regions(key, regions, scope, icon, flags)


    @only_ocaml
    def on_selection_modified(self, view):
        global enclosing
        self.display_errors(view)
        enclosing[view.id()] = None

    def display_errors(self, view):
        """
        Display error message to the status bar when the selection intersects
        with errors in the current view.
        """

        view.erase_phantoms("merlin_error_phantom")

        caret_region = view.sel()[0]

        for message_region, message_text in self.error_messages:
            if message_region.intersects(caret_region):
                phantom_type = "warning" if message_text[:7] == "Warning" else "error"
                message_lines = message_text.split("\n")
                wrapped_message = "<br />".join("<br />".join(textwrap.wrap(message_line, 80, break_long_words=False)) for message_line in message_lines)
                print(wrapped_message)
                phantom_content = phantom_style + "<div class='merlin-phantom merlin-" + phantom_type + "'>" + wrapped_message + "</div>"
                view.add_phantom("merlin_error_phantom", sublime.Region(message_region.end(), message_region.end()), phantom_content, sublime.LAYOUT_BLOCK)

