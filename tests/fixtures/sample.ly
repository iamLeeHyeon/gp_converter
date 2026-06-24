\version "2.26.0"

\header {
  title = "C Major Scale"
  composer = ""
  tagline = ##f
}

\score {
  \new Staff {
    \clef treble
    \time 4/4
    c'4 d'4 e'4 f'4 |
    g'4 a'4 b'4 c''4 |
    \bar "|."
  }
  \layout { }
}
