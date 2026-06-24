\version "2.26.0"
\header { title = "Tab Test" tagline = ##f }
music = \relative c' {
  c4 d e\2 f | g a b c | c b a g | f e\2 d c |
  c4 d e\2 f | g a b c | c b a g | f e\2 d c
}
\score {
  <<
    \new Staff { \clef "treble" \time 4/4 \music }
    \new TabStaff { \music }
  >>
  \layout { }
}
