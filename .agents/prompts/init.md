# Kicking off the toolshed project

Hello coding agent!

You find yourself in a new workspace with the task of implementing the project
`toolshed` as described in `.agents/workspace/plans/bin-distribution-separate-repo.md`.
That plan was specified by another agent within a different repository until it
became apparent that its scope warranted its own repository.

That other agent was working in my dotfiles repo, which you can find at
`~/github/chpatton013/dotfiles2` for reference. The plan contains several
references to another project "chiiiirrus", which you can also find at
`~/github/chpatton013/chiiiirrus`. Since many of the "USER NOTE" amendments in the
plan specifically dictate that something should be done the way it is done in
chiiiirrus, you should familiarize yourself with that repository to meet my
expectations.

Note that most of `chiiiirrus` is unrelated to this assignment; the `bin/` and
`validator/` directories are where the bulk of the influence comes from.
`chiiiirrus:bin/` is the inspiration for the output of `toolshed`, while
`chiiiirrus:validator/` is a file validation suite that I want to lift directly
into this project, and eventually generalize further (we can defer that until
later).

By the time you are done building toolshed, it should operate as a standalone
project that doesn't have any relationship to the repositories where its ideas
originated.

I encourage you to make all manner of changes to the contents of `.agents/` to
suit your needs as you work on that task. In particular:
* `.agents/AGENTS.md` should eventually read as the primer an agent needs to work
  effectively within this repository.
* `.agents/workspace/` is where you should build and store any worthwhile
  intermediates that won't be part of the primary repo. See
  `.agents/workspace/README.md` for more details.

Go ahead and begin.
