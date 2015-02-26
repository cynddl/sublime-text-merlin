# Merlin for Sublime Text 3

## About

This plugin for Sublime Text 3 allows you to analyse OCaml source code, autocomplete and infer types while writing. It checks automatically for syntax or type errors.

## Installation

First of all, be sure to have [merlin](https://github.com/the-lambda-church/merlin) installed. The current supported version of merlin is 2.0. The shorter way of doing this is with [opam](opam.ocaml.org), an OCaml package manager:

    opam install merlin

Next, install the ‘Merlin’ package using **Package Control**
or clone this repository in your *Packages* folder:

    git clone https://github.com/cynddl/sublime-text-merlin.git Merlin

## Work in Progress

This is an initial port of the vim plugin of merlin. Buffers can be synchronised with merlin, but any edit needs a full refresh between ST and merlin. Projects are not currently supported.

If you want to use fully merlin with Sublime Text, fork this repository and contribute!

## License

Sublime-Text-Merlin is licensed under the MIT License. See the file LICENSE.md for more details.
