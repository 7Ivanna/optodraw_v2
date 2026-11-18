# TikZ for LaTeX: \input this file and the figure takes the paper's own font
tikz = scene.render_tikz(standalone=False)
print(tikz[:700], "...")
