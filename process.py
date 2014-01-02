import subprocess
import json

import sublime

from .helpers import merlin_bin


class MerlinExc(Exception):
    """ Exception returned by merlin. """

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Failure(MerlinExc):
    """ Failure exception. """
    pass


class Error(MerlinExc):
    """ Error exception. """
    pass


class MerlinException(MerlinExc):
    """ Standard exception. """
    pass


class MerlinProcess(object):
    """
    This class launches a merlin process and send/receive commands to
    synchronise buffer, autocomplete...
    """

    def __init__(self):
        self.mainpipe = None

    def restart(self):
        if self.mainpipe:
            try:
                try:
                    self.mainpipe.terminate()
                except OSError:
                    pass
                self.mainpipe.communicate()
            except OSError:
                pass
        try:
            user_settings = sublime.load_settings("Merlin.sublime-settings")
            flags = user_settings.get('flags')
            command = [merlin_bin(), '-ignore-sigint']
            command.extend(flags)
            self.mainpipe = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
            )
        except OSError as e:
            print("Failed starting ocamlmerlin. Please ensure that ocamlmerlin \
                   binary is executable.")
            raise e

    def send_command(self, *cmd):
        """
        Send a command to merlin and wait to return the results.
        Raise an exception if merlin returned an error message.
        """

        if self.mainpipe is None or self.mainpipe.returncode is not None:
            self.restart()
        self.mainpipe.stdin.write(json.dumps(cmd).encode('utf-8'))
        line = self.mainpipe.stdout.readline()
        result = json.loads(line.decode('utf-8'))
        content = None
        if len(result) == 2:
            content = result[1]

        if result[0] == "return":
            return content
        elif result[0] == "failure":
            raise Failure(content)
        elif result[0] == "error":
            raise Error(content)
        elif result[0] == "exception":
            raise MerlinException(content)

    def reload(self, full=False):
        if full:
            return self.send_command("refresh")
        else:
            return self.send_command("refresh", "quick")

    def reset(self, name=None):
        if name:
            r = self.send_command("reset", "name", name)
        else:
            r = self.send_command("reset")
        if name == "myocamlbuild.ml":
            self.find_use("ocamlbuild")
        return r

    def tell(self, kind, content):
        """ Send content for the current buffer. """
        if content is None:
            return self.send_command("tell", "end")
        elif type(content) is list:
            return self.send_command("tell", kind, "\n".join(content) + "\n")
        else:
            return self.send_command("tell", kind, content)

    def complete_cursor(self, base, line, col):
        """ Return possible completions at the current cursor position. """
        pos = {'line': line, 'col': col}
        return self.send_command("complete", "prefix", base, "at", pos)

    def report_errors(self):
        """
        Return all errors detected by merlin while parsing the current file.
        """
        return self.send_command("errors")

    def find_list(self):
        """ List all possible external modules to load. """
        return self.send_command('find', 'list')

    def find_use(self, *packages):
        """ Find and load external modules. """
        return self.send_command('find', 'use', packages)

    def project_find(self, project_path):
        """
        Detect .merlin file in the current project and load dependancies.
        """
        return self.send_command("project", "find", project_path)
