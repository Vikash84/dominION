"""
Copyright 2018 Markus Haak (markus.haak@posteo.net)
https://github.com/MarkusHaak/GridIONwatcher

This file is part of GridIONwatcher. GridIONwatcher is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version. GridIONwatcher is distributed in
the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details. You should have received a copy of the GNU General Public License along with GridIONwatcher. If
not, see <http://www.gnu.org/licenses/>.
"""

import logging
import os
import shutil
import argparse

# define logging configuration once for all submudules
logging.basicConfig(level=logging.INFO,
						format='[%(asctime)s] %(message)s',
						datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

package_dir = os.path.dirname(os.path.abspath(__file__))

class ArgHelpFormatter(argparse.HelpFormatter):
	'''
	Formatter adding default values to help texts.
	'''
	def __init__(self, prog):
		super().__init__(prog)

	## https://stackoverflow.com/questions/3853722
	#def _split_lines(self, text, width):
	#	if text.startswith('R|'):
	#		return text[2:].splitlines()  
	#	# this is the RawTextHelpFormatter._split_lines
	#	return argparse.HelpFormatter._split_lines(self, text, width)

	def _get_help_string(self, action):
		text = action.help
		if 	action.default is not None and \
			action.default != argparse.SUPPRESS and \
			'default' not in text.lower():
			text += ' (default: {})'.format(action.default)
		return text

class r_file(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		to_test=values
		if not os.path.isfile(to_test):
			raise argparse.ArgumentTypeError('ERR: {} is not a file'.format(to_test))
		if not os.access(to_test, os.R_OK):
			raise argparse.ArgumentTypeError('ERR: {} is not readable'.format(to_test))
		setattr(namespace,self.dest,to_test)

class r_dir(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		to_test=values
		if not os.path.isdir(to_test):
			raise argparse.ArgumentTypeError('ERR: {} is not a directory'.format(to_test))
		if not os.access(to_test, os.R_OK):
			raise argparse.ArgumentTypeError('ERR: {} is not readable'.format(to_test))
		setattr(namespace,self.dest,to_test)

class w_dir(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		to_test=values
		if not os.path.isdir(to_test):
			raise argparse.ArgumentTypeError('ERR: {} is not a directory'.format(to_test))
		if not os.access(to_test, os.W_OK):
			raise argparse.ArgumentTypeError('ERR: {} is not writeable'.format(to_test))
		setattr(namespace,self.dest,to_test)

class rw_dir(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		to_test=values
		if not os.path.exists(to_test):
			os.makedirs(to_test)
		if not os.path.isdir(to_test):
			raise argparse.ArgumentTypeError('ERR: {} is not a directory'.format(to_test))
		if not os.access(to_test, os.R_OK):
			raise argparse.ArgumentTypeError('ERR: {} is not readable'.format(to_test))
		if not os.access(to_test, os.W_OK):
			raise argparse.ArgumentTypeError('ERR: {} is not writeable'.format(to_test))
		setattr(namespace,self.dest,to_test)

def tprint(*args, **kwargs):
	if not QUIET:
		print("["+strftime("%H:%M:%S", gmtime())+"] "+" ".join(map(str,args)), **kwargs)
	sys.stdout.flush()