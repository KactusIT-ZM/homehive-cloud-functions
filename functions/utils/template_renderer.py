import os
import jinja2

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
template_loader = jinja2.FileSystemLoader(searchpath=template_dir)
template_env = jinja2.Environment(loader=template_loader)
