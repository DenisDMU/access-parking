# Police du dashboard

`MesloLGS-NF-Regular.woff2` et `MesloLGS-NF-Bold.woff2` : **MesloLGS NF**
(Meslo LG par André Berg, variante « Nerd Font » distribuée avec
powerlevel10k), réduite aux caractères latins utilisés par le dashboard
(~15 Ko par fichier, au lieu de ~2,5 Mo).

Meslo LG est publiée sous licence **Apache 2.0** ; elle dérive de Menlo
(Apple) et de Bitstream Vera Sans Mono.
Source : https://github.com/andreberg/Meslo-Font

Sous-ensemble généré avec `pyftsubset` (fonttools) :

    pyftsubset "MesloLGS NF Regular.ttf" --flavor=woff2 --layout-features='*' \
      --unicodes="U+0020-007E,U+00A0-00FF,U+0152,U+0153,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2022,U+2026,U+20AC,U+2190-2193"
