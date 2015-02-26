"""
This module allows you to analyse OCaml source code, autocomplete and infer types while writing
"""

import functools
import sublime
import sublime_plugin
import re
import os
import sys

if sys.version_info < (3, 0):
    from merlin.process import MerlinProcess
    from merlin.helpers import merlin_pos, only_ocaml, clean_whitespace
else:
    from .merlin.process import MerlinProcess
    from .merlin.helpers import merlin_pos, only_ocaml, clean_whitespace

running_process = None


def merlin_process(name):
    global running_process
    if running_process is None:
        running_process = MerlinProcess()
    return running_process.acquire(name)


class MerlinLoadPackage(sublime_plugin.WindowCommand):
    """
    Command to find packages and load them into the current view.
    """

    def run(self):
        view = self.window.active_view()
        self.process = merlin_process(view.file_name())

        self.modules = self.process.find_list()
        self.window.show_quick_panel(self.modules, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.process.find_use(self.modules[index])


class MerlinAddBuildPath(sublime_plugin.WindowCommand):
    """
    Command to add a directory to the build path (for completion, typechecking, etc).
    """

    def run(self):
        view = self.window.active_view()
        file_name = view.file_name()
        self.process = merlin_process(file_name)

        if file_name:
            wd = os.path.dirname(os.path.abspath(file_name))
        else:
            wd = os.getcwd()

        self.window.show_input_panel("Add build path", wd, self.on_done, None, None)

    def on_done(self, directory):
        self.process.add_build_path(directory)


class MerlinAddSourcePath(sublime_plugin.WindowCommand):
    """
    Command to add a directory to the source path (for jumping to definition).
    """

    def run(self):
        view = self.window.active_view()
        file_name = view.file_name()
        self.process = merlin_process(file_name)

        if file_name:
            wd = os.path.dirname(os.path.abspath(file_name))
        else:
            wd = os.getcwd()

        self.window.show_input_panel("Add source path", wd, self.on_done, None, None)

    def on_done(self, directory):
        self.process.add_source_path(directory)


class MerlinRemoveBuildPath(sublime_plugin.WindowCommand):
    """
    Command to remove a directory from the build path.
    """

    def run(self):
        view = self.window.active_view()
        self.process = merlin_process(view.file_name())

        self.directories = self.process.list_build_path()
        self.window.show_quick_panel(self.directories, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.process.remove_build_path(self.directories[index])


class MerlinRemoveSourcePath(sublime_plugin.WindowCommand):
    """
    Command to remove a directory from the source path.
    """

    def run(self):
        view = self.window.active_view()
        self.process = merlin_process(view.file_name())

        self.directories = self.process.list_source_path()
        self.window.show_quick_panel(self.directories, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.process.remove_source_path(self.directories[index])


class MerlinEnableExtension(sublime_plugin.WindowCommand):
    """
    Enable syntax extension
    """

    def run(self):
        view = self.window.active_view()
        self.process = merlin_process(view.file_name())

        self.extensions = self.process.extension_list('disabled')
        self.window.show_quick_panel(self.extensions, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.process.extension_enable([self.extensions[index]])


class MerlinDisableExtension(sublime_plugin.WindowCommand):
    """
    Disable syntax extension
    """

    def run(self):
        view = self.window.active_view()
        self.process = merlin_process(view.file_name())

        self.extensions = self.process.extension_list('enabled')
        self.window.show_quick_panel(self.extensions, self.on_done)

    def on_done(self, index):
        if index != -1:
            self.process.extension_disable([self.extensions[index]])


class MerlinTypeEnclosing:
    """
    Return type information around cursor.
    """

    def __init__(self, view):
        process = merlin_process(view.file_name())
        process.sync_buffer_to_cursor(view)

        pos = view.sel()
        line, col = view.rowcol(pos[0].begin())

        # FIXME: proper integration into sublime-text
        # enclosing is a list of json objects of the form:
        # { 'type': string;
        #   'tail': "no"|"position"|"call" // tailcall information
        #   'start', 'end': {'line': int, 'col': int}
        # }
        self.enclosing = process.type_enclosing(line + 1, col)
        self.view = view

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

    def show_panel(self):
        self.view.window().show_quick_panel(self._items(), self.on_done, sublime.MONOSPACE_FONT)

    def show_menu(self):
        self.view.show_popup_menu(self._items(), self.on_done, sublime.MONOSPACE_FONT)

    def on_done(self, index):
        if index > -1:
            sel = self.view.sel()
            sel.clear()
            sel.add(self._item_region(self.enclosing[index]))


class MerlinTypeCommand(sublime_plugin.WindowCommand):
    """
    Return type information around cursor.
    """
    def run(self):
        enclosing = MerlinTypeEnclosing(self.view)
        enclosing.show_panel()


class MerlinTypeMenu(sublime_plugin.TextCommand):
    """
    Display type information in context menu
    """
    def run(self, edit):
        enclosing = MerlinTypeEnclosing(self.view)
        enclosing.show_menu()


def merlin_locate_result(result, window):
    if isinstance(result, dict):
        pos = result['pos']
        if 'file' in result:
            filename = "%s:%d:%d" % (result['file'], pos['line'] - 1, pos['col'] + 1)
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
        process = merlin_process(view.file_name())
        process.sync_buffer_to_cursor(view)

        pos = view.sel()
        line, col = view.rowcol(pos[0].begin())
        merlin_locate_result(process.locate(line + 1, col, kind=self.kind()), self.window)

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
        process = merlin_process(view.file_name())
        process.sync_buffer_to_cursor(view)

        pos = view.sel()
        line, col = view.rowcol(pos[0].begin())
        merlin_locate_result(process.locate(line + 1, col, ident=name), self.window)


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
        self.process = merlin_process(view.file_name())

        self.files = self.process.which_with_ext(self.extensions())
        self.window.show_quick_panel(self.files, self.on_done)

    def on_done(self, index):
        if index != -1:
            module_name = self.files[index]
            modules = map(lambda ext: module_name + ext, self.extensions())
            self.window.open_file(self.process.which_path(list(modules)))


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

        process = merlin_process(view.file_name())
        process.sync_buffer_to_cursor(view)

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
            result = process.complete_cursor(prefix, line + 1, col)
            self.cplns = [(clean_whitespace(r['name'] + '\t' + r['desc']), r['name']) for r in result]

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
        ret = self.view != None and self.view.window() != None
        if ret and window:
            ret = self.view.window().id() == window.id()
        return ret

    def flush(self):
        self.view.set_read_only(False)
        self.view.set_scratch(True)
        self.view.run_command("merlin_error_panel_flush", {"data": self.data})
        self.view.set_read_only(True)

    def open(self, window=None):
        if window == None:
            window = sublime.active_window()
        if not self.is_visible(window):
            self.view = window.get_output_panel("merlin")
            self.view.settings().set("result_file_regex", "^(.+):([0-9]+):([0-9]+)")
            #self.view.set_syntax_file(fileName)
        self.flush()

        window.run_command("show_panel", {"panel": "output.merlin"})

    def close(self):
        sublime.active_window().run_command("hide_panel", {"panel": "output.merlin"})

merlin_error_panel = MerlinErrorPanel()

class MerlinBuffer(sublime_plugin.EventListener):
    """
    Synchronize the current buffer with Merlin and:
     - autocomplete words with type informations;
     - display errors in the gutter.
    """

    _process = None
    error_messages = []

    def process(self, view):
        if not self._process:
            self._process = merlin_process(view.file_name())
        return self._process

    #@only_ocaml
    #def on_activated(self, view):
    #    """
    #    Create a Merlin process if necessary and load imported modules.
    #    """

    #    self.show_errors(view)

    @only_ocaml
    def on_post_save(self, view):
        """
        Sync the buffer with Merlin on each text edit.
        """

        self.process(view).sync_buffer(view)  # Dummy sync with the whole file
        self.display_in_error_panel(view)
        self.show_errors(view)

    @only_ocaml
    def on_modified(self, view):
        view.erase_regions('ocaml-underlines-errors')

    def gutter_icon_path(self):
        try:
            resource = sublime.load_binary_resource("gutter-icon.png")

            cache_path = os.path.join(sublime.cache_path(), "Merlin", "gutter-icon.png")
            if not os.path.isfile(cache_path):
                if not os.path.isdir(os.path.dirname(cache_path)):
                    os.makedirs(os.path.dirname(cache_path))
                f = open(cache_path, "wb")
                f.write(resource)
                f.close()

            return "Cache/Merlin/gutter-icon.png"

        except IOError:
            return "Packages/Merlin/gutter-icon.png"

    def show_errors(self, view):
        """
        Show a simple gutter icon for each parsing error.
        """

        view.erase_regions('ocaml-underlines-errors')

        errors = self.process(view).report_errors()

        error_messages = []
        underlines = []

        for e in errors:
            if 'start' in e and 'end' in e:
                pos_start = e['start']
                pos_stop = e['end']
                pnt_start = merlin_pos(view, pos_start)
                pnt_stop = merlin_pos(view, pos_stop)
                r = sublime.Region(pnt_start, pnt_stop)
                line_r = view.full_line(r)
                line_r = sublime.Region(line_r.a - 1, line_r.b)
                underlines.append(r)

                # Remove line and character number
                message = e['message']

                error_messages.append((line_r, message))

        self.error_messages = error_messages
        flag = sublime.DRAW_OUTLINED
        # add_regions(key, regions, scope, icon, flags)
        view.add_regions('ocaml-underlines-errors', underlines, 'invalid', self.gutter_icon_path(), flag)

    @only_ocaml
    def on_selection_modified(self, view):
        self.display_in_error_panel(view)

    def display_in_error_panel(self, view):
        """
        Display error message to the status bar when the selection intersects
        with errors in the current view.
        """

        caret_region = view.sel()[0]

        for message_region, message_text in self.error_messages:
            if message_region.intersects(caret_region):
                merlin_error_panel.open()
                merlin_error_panel.set_data(message_text)
