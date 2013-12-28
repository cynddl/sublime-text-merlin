import functools
import sublime
import sublime_plugin

from .process import *
from .helpers import *


merlin_processes = {}


def merlin_process(name):
    global merlin_processes
    if name is None:
        name = ''

    if name not in merlin_processes:
        merlin_processes[name] = MerlinProcess()

    return merlin_processes[name]


class Autocomplete(sublime_plugin.EventListener):
    """
    Sublime Text autocompletion integration
    """

    completions = []
    cplns_ready = None

    @only_ocaml
    def on_query_completions(self, view, prefix, locations):
        """ Sublime autocomplete event handler. """

        process = merlin_process(view.file_name())

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
            result = process.complete_cursor(prefix, line, col)
            self.cplns = [(r['name'] + '\t' + r['desc'], r['name']) for r in result]

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


class MerlinBuffer(sublime_plugin.EventListener):
    """
    Synchronize the current buffer with Merlin and:
     - autocomplete words with type informations;
     - display errors in the gutter.
    """

    process = None
    error_messages = []

    @only_ocaml
    def on_activated(self, view):
        self.process = merlin_process(view.file_name())

    @only_ocaml
    def on_modified(self, view):
        """
        Sync the buffer with Merlin on each text edit.
        """

        self.process.reset()
        self.sync_buffer(view)  # Dummy sync with the whole file
        self.display_to_status_bar(view)

    @only_ocaml
    def on_modified_async(self, view):
        self.show_errors(view)

    @only_ocaml
    def sync_buffer(self, view):
        """
        Performs a dummy sync by reloading the whole buffer.
        """
        content = sublime.Region(0, view.size())
        lines = view.split_by_newlines(content)

        self.process.tell('source', [view.substr(l) for l in lines])
        self.process.tell('source', None)  # EOF

    def show_errors(self, view):
        """
        Show a simple gutter icon for each parsing error.
        """
        view.erase_regions('ocaml-errors')

        errors = self.process.report_errors()

        error_messages = []
        underlines = []

        for e in errors:
            pos_start = e['start']
            pos_stop = e['end']
            pnt_start = merlin_pos(view, pos_start)
            pnt_stop = merlin_pos(view, pos_stop)
            r = sublime.Region(pnt_start, pnt_stop)
            line_r = view.full_line(r)
            line_r.a -= 1
            underlines.append(r)

            # Remove line and character number
            message = e['message']
            print(message)

            error_messages.append((line_r, message))

        self.error_messages = error_messages
        flag = sublime.DRAW_OUTLINED
        view.add_regions('ocaml-underlines-errors', underlines, scope='ocaml-underlines-errors', icon='dot', flags=flag)

    @only_ocaml
    def on_selection_modified(self, view):
        self.display_to_status_bar(view)

    def display_to_status_bar(self, view):
        caret_region = view.sel()[0]

        for message_region, message_text in self.error_messages:
            if message_region.intersects(caret_region):
                sublime.status_message(message_text)
                return
            else:
                sublime.status_message('')