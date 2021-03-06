"""
Copyright 2018 Markus Haak (markus.haak@posteo.net)
https://github.com/MarkusHaak/dominION

This file is part of dominION. dominION is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version. dominION is distributed in
the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
details. You should have received a copy of the GNU General Public License along with dominION. If
not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import os
import sys
import time
from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler
from watchdog.events import FileSystemEventHandler
#import multiprocessing as mp
from collections import OrderedDict
import re
import copy
import json
import subprocess
#import sched
import webbrowser
from shutil import copyfile, which
import dateutil
from datetime import datetime
from operator import itemgetter
from .version import __version__
from .statsparser import get_argument_parser as sp_get_argument_parser
from .statsparser import parse_args as sp_parse_args
from .helper import initLogger, resources_dir, get_script_dir, hostname, ArgHelpFormatter, r_file, r_dir, rw_dir, defaults, jinja_env
import threading
import logging
import queue
from pathlib import Path
from jinja2 import Environment, PackageLoader, select_autoescape

ALL_RUNS = {}
ALL_RUNS_LOCK = threading.RLock()
SP_DIRS = {}
SP_DIRS_LOCK = threading.RLock()
MUX_RESULTS = {}
MUX_RESULTS_LOCK = threading.RLock()
UPDATE_OVERVIEW = False
UPDATE_OVERVIEW_LOCK = threading.RLock()
logger = None

class parse_statsparser_args(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		to_test = values.split(' ')
		argument_parser = sp_get_argument_parser()
		args = sp_parse_args(argument_parser, to_test)
		setattr(namespace,self.dest,to_test)

def parse_args():
	parser = argparse.ArgumentParser(description='''A tool for monitoring and protocoling sequencing runs 
												 performed on the Oxford Nanopore Technologies GridION 
												 sequencer and for automated post processing and transmission 
												 of generated data. It collects information on QC and 
												 sequencing experiments and displays summaries of mounted 
												 flow cells as well as comprehensive reports about currently 
												 running and previously performed experiments.''',
									 formatter_class=ArgHelpFormatter, 
									 add_help=False)

	general_group = parser.add_argument_group('General arguments', 
											  "arguments for advanced control of the program's behavior")

	general_group.add_argument('-n', '--no_transfer',
							   action='store_true',
							   help='''no data transfer to the remote host''')
	general_group.add_argument('-a', '--all_fast5',
							   action='store_true',
							   help='''also put fast5 files of reads removed by length and quality 
							           filtering into barcode bins''')
	general_group.add_argument('-p', '--pass_only',
							   action='store_true',
							   help='''use data from fastq_pass only''')
	general_group.add_argument('-l', '--min_length',
							   type=int,
							   default=1000,
							   help='''minimal length to pass filter''')
	general_group.add_argument('-r', '--min_length_rna',
							   type=int,
							   default=50,
							   help='''minimal length to pass filter for rna libraries''')
	general_group.add_argument('-q', '--min_quality',
							   type=int,
							   default=5,
							   help='''minimal quality to pass filter''')
	general_group.add_argument('-d', '--rsync_dest',
							   default="{}@{}:{}".format(defaults()["user"], defaults()["host"], defaults()["dest"]),
							   help='''destination for data transfer with rsync, format USER@HOST[:DEST].
							           Key authentication for the specified destination must be set up (see option -i),
							           otherwise data transfer will fail. Default value is parsed from setting
							           file {}'''.format(os.path.join(resources_dir, "defaults.ini")))
	general_group.add_argument('-i', '--identity_file',
							   default="{}".format(defaults()["identity"]),
							   help='''file from which the identity (private key) for public key authentication is read.
							           Default value is parsed from setting file {}'''.format(os.path.join(resources_dir, "defaults.ini")))
	general_group.add_argument('--bc_kws',
							   nargs='*',
							   default=['RBK', 'NBD', 'RAB', 'LWB', 'PBK', 'RPB', 'arcod'],
							   help='''if at least one of these key words is a substring of the run name,
									   porechop is used to demultiplex the fastq data''')
	general_group.add_argument('-u', '--update_interval',
							   type=int,
							   default=300,
							   help='minimum time interval in seconds for updating the content of a report page')
	general_group.add_argument('-m', '--ignore_file_modifications',
							   action='store_true',
							   help='''Ignore file modifications and only consider file creations regarding 
							           determination of the latest log files''')

	io_group = parser.add_argument_group('I/O arguments', 
										 'Further input/output arguments. Only for special use cases')
	io_group.add_argument('-o', '--output_dir',
						  action=rw_dir,
						  default="/data/dominION/",
						  help='Path to the base directory where experiment reports shall be saved')
	arg_data_basedir = \
	io_group.add_argument('--data_basedir',
						  action=rw_dir,
						  default='/data',
						  help='Path to the directory where basecalled data is saved')
	io_group.add_argument('--minknow_log_basedir',
						  action=r_dir,
						  default='/var/log/MinKNOW',
						  help='''Path to the base directory of GridIONs log files''')

	io_group.add_argument('--logfile',
						  help='''File in which logs will be safed 
						  (default: OUTPUTDIR/logs/YYYY-MM-DD_hh:mm_HOSTNAME_LOGLVL.log''')

	sp_arguments = parser.add_argument_group('Statsparser arguments',
										   'Arguments passed to statsparser for formatting html reports')
	sp_arguments.add_argument('--statsparser_args',
							action=parse_statsparser_args,
							default=[],
							help='''Arguments that are passed to the statsparser script.
								   See a full list of available arguments with --statsparser_args " -h" ''')

	help_group = parser.add_argument_group('Help')
	help_group.add_argument('-h', '--help', 
							action='help', 
							default=argparse.SUPPRESS,
							help='Show this help message and exit')
	help_group.add_argument('--version', 
							action='version', 
							version=__version__,
							help="Show program's version string and exit")
	help_group.add_argument('-v', '--verbose',
							action='store_true',
							help='Additional debug messages are printed to stdout')
	help_group.add_argument('--quiet',
							action='store_true',
							help='Only errors and warnings are printed to stdout')

	args = parser.parse_args()


	ns = argparse.Namespace()
	arg_data_basedir(parser, ns, args.data_basedir, '')

	if not os.path.exists(args.identity_file):
		print("Identity file {} does not exists. Please check key authentication settings or specify a different key with option -i.".format(args.identity_file))
		exit()

	args.watchnchop_args = []
	if args.no_transfer:
		args.watchnchop_args.append('-n')
	if args.all_fast5:
		args.watchnchop_args.append('-a')
	if args.pass_only:
		args.watchnchop_args.append('-p')
	#args.watchnchop_args.extend(['-l', str(args.min_length)])
	#args.watchnchop_args.extend(['-r', str(args.min_length_rna)])
	args.watchnchop_args.extend(['-q', str(args.min_quality)])
	args.watchnchop_args.extend(['-d', args.rsync_dest])
	args.watchnchop_args.extend(['-i', args.identity_file])

	return args


def main(args):
	global ALL_RUNS
	global ALL_RUNS_LOCK
	global UPDATE_OVERVIEW
	global logger

	for p in [args.output_dir,
			  os.path.join(args.output_dir, 'runs'),
			  os.path.join(args.output_dir, 'qc'),
			  os.path.join(args.output_dir, 'logs')]:
		if not os.path.exists(p):
			os.makedirs(p)

	if args.verbose:
		loglvl = logging.DEBUG
	elif args.quiet:
		loglvl = logging.WARNING
	else:
		loglvl = logging.INFO
	if not args.logfile:
		logs_filename = "{}_{}_{}.log".format(datetime.now().strftime("%Y-%m-%d_%H:%M"), hostname, loglvl)
		args.logfile = os.path.join(args.output_dir, 'logs', logs_filename)
	initLogger(logfile=args.logfile, level=loglvl)

	logger = logging.getLogger(name='gw')
	logger.info("##### starting dominION {} #####\n".format(__version__))

	
	logger.info("setting up dominION status page environment")
	if not os.path.exists(os.path.join(args.output_dir, 'res')):
		os.makedirs(os.path.join(args.output_dir, 'res'))
	for res_file in ['style.css', 'flowcell.png', 'no_flowcell.png']:
		copyfile(os.path.join(resources_dir, res_file), 
				 os.path.join(args.output_dir, 'res', res_file))

	import_qcs(os.path.join(args.output_dir, "qc"))
	import_runs(os.path.join(args.output_dir, "runs"))

	logger.info("starting to observe runs directory for changes to directory names")
	observed_dir = os.path.join(args.output_dir, 'runs')
	event_handler = RunsDirsEventHandler(observed_dir)
	observer = Observer()
	observer.schedule(event_handler, 
					  observed_dir, 
					  recursive=True)
	observer.start()

	logger.info("starting channel watchers:")
	watchers = []
	for channel in range(5):
		watchers.append(Watcher(args.minknow_log_basedir, 
								channel, 
								args.ignore_file_modifications, 
								args.output_dir, 
								args.data_basedir, 
								args.statsparser_args,
								args.update_interval,
								args.watchnchop_args,
								args.min_length,
								args.min_length_rna,
								args.bc_kws))

	logger.info("initiating dominION overview page")
	update_overview(watchers, args.output_dir)
	webbrowser.open('file://' + os.path.realpath(os.path.join(args.output_dir, "{}_overview.html".format(hostname))))
	logger.info("entering main loop")
	try:
		n = 0
		while True:
			for watcher in watchers:
				watcher.check_q()
			if UPDATE_OVERVIEW:
				update_overview(watchers, args.output_dir)
				UPDATE_OVERVIEW = False
			time.sleep(0.2)
			n += 1
			if n == 100:
				n = 0
				set_update_overview()
	except KeyboardInterrupt:
		for watcher in watchers:
			watcher.observer.stop()
			if watcher.spScheduler.is_alive() if watcher.spScheduler else None:
				watcher.stop_statsparser(0.05)
			for wcScheduler in watcher.wcScheduler:
				if wcScheduler.is_alive() if wcScheduler else None:
					wcScheduler.join(timeout=0.05)
	for watcher in watchers:
		logger.info("joining GA{}0000's observer".format(watcher.channel))
		watcher.observer.join()
		for wcScheduler in watcher.wcScheduler:
			if wcScheduler.is_alive() if wcScheduler else None:
				logger.info("joining GA{}0000's watchnchop scheduler".format(watcher.channel))
				wcScheduler.join()
	for watcher in watchers:
		if watcher.spScheduler.is_alive() if watcher.spScheduler else None:
			logger.info("joining GA{}0000's statsparser scheduler".format(watcher.channel))
			watcher.stop_statsparser()

def set_update_overview():
	global UPDATE_OVERVIEW
	UPDATE_OVERVIEW_LOCK.acquire()
	UPDATE_OVERVIEW = True
	UPDATE_OVERVIEW_LOCK.release()

def add_database_entry(flowcell, run_data, mux_scans):
	ALL_RUNS_LOCK.acquire()
	#TODO: check for all mandatory entries
	asic_id_eeprom = flowcell['asic_id_eeprom']
	run_id = run_data['run_id']
	if asic_id_eeprom in ALL_RUNS:
		if run_id in ALL_RUNS[asic_id_eeprom]:
			logger.warning("{} exists multiple times in database!".format(run_id))
			logger.warning("conflicting runs: {}, {}".format(ALL_RUNS[asic_id_eeprom][run_id]['run_data']['relative_path'],
															 run_data['relative_path']))
			ALL_RUNS_LOCK.release()
			return False
	else:
		ALL_RUNS[asic_id_eeprom] = {}
	
	ALL_RUNS[asic_id_eeprom][run_id] = {'flowcell'	: flowcell,
										'run_data'	: run_data,
										'mux_scans'	: mux_scans}
	logger.debug('{} - added experiment of type "{}" performed on flowcell "{}" on "{}"'.format(asic_id_eeprom, 
																								run_data['experiment_type'], 
																								flowcell['flowcell_id'], 
																								run_data['protocol_start']))
	ALL_RUNS_LOCK.release()
	return True

def add_mux_scan_results(flowcell_data, mux_scans):
	MUX_RESULTS_LOCK.acquire()
	asic_id_eeprom = flowcell_data['asic_id_eeprom']
	flowcell_id = flowcell_data['flowcell_id']
	if asic_id_eeprom not in MUX_RESULTS:
		MUX_RESULTS[asic_id_eeprom] = []
	for mux_scan in mux_scans:
		mux_scan_copy = copy.deepcopy(mux_scan)
		if not 'total' in mux_scan:
			if 'group * total' in mux_scan:
				mux_scan_copy['total'] = mux_scan['group * total']
				del mux_scan_copy['group * total']
			else:
				continue
		mux_scan_copy['flowcell_id'] = flowcell_id
		mux_scan_copy['timestamp'] = dateutil.parser.parse(mux_scan['timestamp'])
		for i in range(len(MUX_RESULTS[asic_id_eeprom])):
			if mux_scan_copy['timestamp'] < MUX_RESULTS[asic_id_eeprom][i]['timestamp']:
				MUX_RESULTS[asic_id_eeprom].insert(i, mux_scan_copy)
				break
		else:
			MUX_RESULTS[asic_id_eeprom].append(mux_scan_copy)
	MUX_RESULTS_LOCK.release()

def import_qcs(qc_dir):
	logger.info("importing platform qc entries from files in directory {}".format(qc_dir))
	for fp in [os.path.join(qc_dir, fn) for fn in os.listdir(qc_dir) if fn.endswith('.json')]:
		if os.path.isfile(fp):
			with open(fp, "r") as f:
				try:
					flowcell, run_data, mux_scans = json.loads(f.read(), object_pairs_hook=OrderedDict)
				except:
					logger.warning("failed to parse {}, json format or data structure corrupt".format(fn))
					continue
			asic_id_eeprom = flowcell['asic_id_eeprom']
			add_mux_scan_results(flowcell, mux_scans)

def import_runs(base_dir, refactor=False):
	logger.info("importing sequencing run entries from files in directory {}".format(base_dir))
	for experiment in [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]:
		experiment_dir = os.path.join(base_dir, experiment)
		for sample in [d for d in os.listdir(experiment_dir) if os.path.isdir(os.path.join(experiment_dir, d))]:
			sample_dir = os.path.join(experiment_dir, sample)
			for fp in [os.path.join(sample_dir, fn) for fn in os.listdir(sample_dir) if fn.endswith('.json')]:
				if os.path.isfile(fp):
					with open(fp, "r") as f:
						try:
							flowcell, run_data, mux_scans = json.loads(f.read(), object_pairs_hook=OrderedDict)
						except:
							logger.warning("failed to parse {}, json format or data structure corrupt".format(fn))
							continue
					# temporarily change attributes experiment and sample according to directory names
					prev = (run_data['experiment'] if 'experiment' in run_data else None, 
							run_data['sample'] if 'sample' in run_data else None)
					changed = prev == (experiment, sample)
					run_data['experiment'] = experiment
					run_data['sample'] = sample
					if refactor and changed:
						# make changes permanent
						logging.info("writing changes to attributes 'experiment' and 'sample' to file")
						data = (flowcell, run_data, mux_scans)
						with open( fp, 'w') as f:
							print(json.dumps(data, indent=4), file=f)
					
					if not add_database_entry(flowcell, run_data, mux_scans):
						logger.error("failed to add content from {} to the database".format(fp))
						continue
					# add mux scans
					add_mux_scan_results(flowcell, mux_scans)

def get_runs_by_flowcell(asic_id_eeprom):
	ALL_RUNS_LOCK.acquire()
	runs = {}
	if asic_id_eeprom:
		if asic_id_eeprom in ALL_RUNS:
			for run_id in ALL_RUNS[asic_id_eeprom]:
				if 'qc' not in ALL_RUNS[asic_id_eeprom][run_id]['run_data']['experiment_type'].lower():
					runs[run_id] = ALL_RUNS[asic_id_eeprom][run_id]
	ALL_RUNS_LOCK.release()
	return runs

def get_latest_mux_scan_result(asic_id_eeprom):
	latest_result = None
	MUX_RESULTS_LOCK.acquire()
	if asic_id_eeprom in MUX_RESULTS:
		latest_result =  MUX_RESULTS[asic_id_eeprom][0]
	MUX_RESULTS_LOCK.release()
	return latest_result

def get_latest(runs):
	latest_qc = None
	for run_id in runs:
		if latest_qc:
			_protocol_start = dateutil.parser.parse(runs[latest_qc]['run_data']['protocol_start'])
			if protocol_start > _protocol_start:
				latest_qc = run_id
		else:
			latest_qc = run_id
			protocol_start = dateutil.parser.parse(runs[run_id]['run_data']['protocol_start'])
	return latest_qc

def update_overview(watchers, output_dir):
	channel_to_css = {0:"one", 1:"two", 2:"three", 3:"four", 4:"five"}
	render_dict = {"version"		:	__version__,
				   "dateTimeNow"	:	datetime.now().strftime("%Y-%m-%d_%H:%M"),
				   "channels"		: 	[],
				   "all_exp" 		:	[]
				   }
	for watcher in watchers:
		channel = watcher.channel
		render_dict["channels"].append({})
		asic_id_eeprom = None
		try:
			asic_id_eeprom = watcher.channel_status.flowcell['asic_id_eeprom']
		except:
			pass

		runs = get_runs_by_flowcell(asic_id_eeprom)
		#qcs  = get_qcs_by_flowcell(asic_id_eeprom)

		render_dict["channels"][channel]['latest_qc'] = {}
		latest_qc = get_latest_mux_scan_result(asic_id_eeprom)
		if latest_qc:
			render_dict["channels"][channel]['latest_qc']['timestamp'] 	= latest_qc['timestamp'].date()
			render_dict["channels"][channel]['latest_qc']['total'] 		= latest_qc['total']
			if 'in_use' in latest_qc and watcher.channel_status.sequencing:
				render_dict["channels"][channel]['latest_qc']['in_use'] = latest_qc['in_use']
			else:
				render_dict["channels"][channel]['latest_qc']['in_use'] = 0

		render_dict["channels"][channel]['runs'] = []
		for run_id in runs:
			experiment = runs[run_id]['run_data']['experiment']
			if not experiment:
				if 'user_filename_input' in runs[run_id]['run_data']:
					experiment = runs[run_id]['run_data']['user_filename_input']
				if not experiment:
					logger.WARNING('not adding run with id {} to overview because no experiment name is set'.format(run_id))
			sample = runs[run_id]['run_data']['sample']
			if not sample:
				sample = experiment
			link = os.path.abspath(os.path.join(output_dir,'runs',experiment,sample,'report.html'))
			render_dict["channels"][channel]['runs'].append({'experiment':experiment,
															 'link':link})

		render_dict["channels"][channel]['channel'] = channel_to_css[watcher.channel]
		render_dict["channels"][channel]['asic_id_eeprom'] = asic_id_eeprom
		if asic_id_eeprom:
			if not latest_qc:
				render_dict["channels"][channel]['flowcell_id'] = "NO RECORDS"
			else:
				render_dict["channels"][channel]['flowcell_id'] = latest_qc['flowcell_id']
		else:	
			render_dict["channels"][channel]['flowcell_id'] = '-'

	ALL_RUNS_LOCK.acquire()
	all_runs_info = []
	for asic_id_eeprom in ALL_RUNS:
		for run_id in ALL_RUNS[asic_id_eeprom]:
			experiment_type = ALL_RUNS[asic_id_eeprom][run_id]['run_data']['experiment_type']
			if not 'qc' in experiment_type.lower():
				protocol_start = dateutil.parser.parse(ALL_RUNS[asic_id_eeprom][run_id]['run_data']['protocol_start'])
				duration = "N/A"
				if 'protocol_end' in ALL_RUNS[asic_id_eeprom][run_id]['run_data']:
					if ALL_RUNS[asic_id_eeprom][run_id]['run_data']['protocol_end']:
						protocol_end = dateutil.parser.parse(ALL_RUNS[asic_id_eeprom][run_id]['run_data']['protocol_end'])
						duration = "{}".format(protocol_end - protocol_start).split('.')[0]
				sequencing_kit = ALL_RUNS[asic_id_eeprom][run_id]['run_data']['sequencing_kit']
				experiment = ALL_RUNS[asic_id_eeprom][run_id]['run_data']['experiment']
				sample = ALL_RUNS[asic_id_eeprom][run_id]['run_data']['sample']
				if not sample:
					sample = experiment
				link = os.path.abspath(os.path.join(output_dir,'runs',experiment,sample,'report.html'))
				all_runs_info.append({'link':link,
									  'experiment':experiment,
									  'sample': sample,
									  'sequencing_kit': sequencing_kit,
									  'protocol_start': protocol_start,
									  'duration': duration})
	ALL_RUNS_LOCK.release()

	if all_runs_info:
		all_runs_info = sorted(all_runs_info, key=lambda k: k['protocol_start'], reverse=True)

		run = 0
		sample = 0
		grouped = [[[all_runs_info[0]]]] if all_runs_info else [[[]]]
		for run_info in all_runs_info[1:]:
			if grouped[run][sample][0]['experiment'] == run_info['experiment']:
				if grouped[run][sample][0]['sample'] == run_info['sample']:
					grouped[run][sample].append(run_info)
				else:
					grouped[run].append( [run_info] )
					sample += 1
			else:
				grouped.append( [[run_info]] )
				run += 1
				sample = 0


		for exp in grouped:
			render_dict['all_exp'].append(
				{'num_samples':str(sum([len(sample) for sample in exp])),
				 'experiment':exp[0][0]['experiment'],
				 'samples':[]})
			for sample in exp:
				render_dict['all_exp'][-1]['samples'].append(
					{'num_runs':str(len(sample)),
					 'link':sample[0]['link'],
					 'sample':sample[0]['sample'],
					 'runs':[]})
				for run in sample:
					render_dict['all_exp'][-1]['samples'][-1]['runs'].append(run)

	template = jinja_env.get_template('overview.template')
	with open(os.path.join(output_dir, "{}_overview.html".format(hostname)), 'w') as f:
		print(template.render(render_dict), file=f)

class ChannelStatus():
	empty_run_data = OrderedDict([
		('run_id', None),
		('minion_id', None),
		('sequencing_kit', None),
		('protocol_start', None),
		('protocol_end', None),
		('relative_path', None),
		('sample', None),
		('experiment', None)
		])

	empty_flowcell = OrderedDict([
		('flowcell_id', None),
		('asic_id', None),
		('asic_id_eeprom', None),
		('flowcell', None)
		])

	empty_mux = OrderedDict()

	def __init__(self, minion_id, channel):
		self.minion_id = minion_id
		self.flowcell = copy.deepcopy(self.empty_flowcell)
		self.run_data = copy.deepcopy(self.empty_run_data)
		self.mux_scans = []
		self.run_data['minion_id'] = minion_id
		self.logger = logging.getLogger(name='gw.w{}.cs'.format(channel+1))
		self.sequencing = False

	def update(self, content, overwrite=False):
		for key in content:
			if key in self.flowcell:
				if self.flowcell[key]:
					if overwrite:
						self.logger.info("changing the current value of {} ({}) to {}".format(key, self.flowcell[key], content[key]))
						self.flowcell[key] = content[key]
					else:
						self.logger.debug("not changing the current value of {} ({}) to {}".format(key, self.flowcell[key], content[key]))
					continue
				else:
					self.flowcell[key] = content[key]
					self.logger.info("new flowcell value for {} : {}".format(key, content[key]))
					continue
			elif key in self.run_data:
				if self.run_data[key]:
					if overwrite:
						self.logger.info("changing the current value of {} ({}) to {}".format(key, self.run_data[key], content[key]))
						self.run_data[key] = content[key]
					else:
						self.logger.debug("not changing the current value of {} ({}) to {}".format(key, self.run_data[key], content[key]))
					continue
			self.run_data[key] = content[key]
			self.logger.info("new run value for {} : {}".format(key, content[key]))

	def add_mux_scan(self, timestamp, active_pores, in_use=None):
		self.mux_scans.append(copy.deepcopy(self.empty_mux))
		self.mux_scans[-1]['timestamp'] = timestamp
		self.mux_scans[-1]['total'] = active_pores
		if in_use:
			self.mux_scans[-1]['in_use'] = in_use
		add_mux_scan_results(self.flowcell, [self.mux_scans[-1]])
		self.logger.debug("added new mux scan result")

	def flowcell_disconnected(self):
		self.logger.info("resetting flowcell and run data")
		self.flowcell = copy.deepcopy(self.empty_flowcell)
		self.run_data = copy.deepcopy(self.empty_run_data)
		self.run_data['minion_id'] = self.minion_id
		self.mux_scans = []
		self.sequencing = False

	def reset_channel(self):
		self.logger.info("resetting run data")
		self.run_data = copy.deepcopy(self.empty_run_data)
		self.run_data['minion_id'] = self.minion_id
		self.mux_scans = []
		self.sequencing = False


class WatchnchopScheduler(threading.Thread):
	def __init__(self, data_basedir, relative_path, experiment, sequencing_kit, fastq_reads_per_file,
				 bc_kws, stats_fp, channel, watchnchop_args, min_length, min_length_rna):
		threading.Thread.__init__(self)
		if getattr(self, 'daemon', None) is None:
			self.daemon = True
		else:
			self.setDaemon(True)
		self.stoprequest = threading.Event()	# set when joined without timeout (eg if terminated with ctr-c)
		self.exp_end = threading.Event()			# set when joined with timeout (eg if experiment ended)
		self.logger = logging.getLogger(name='gw.w{}.wcs'.format(channel+1))

		self.observed_dir = os.path.join(data_basedir, relative_path, 'fastq_pass')
		# define the command that is to be executed
		self.cmd = [which('perl'),
					which('watchnchop'),
					'-o', stats_fp,
					'-f', str(fastq_reads_per_file)]
		if watchnchop_args:
			self.cmd.extend(watchnchop_args)
		for kw in bc_kws:
			if kw.lower() in experiment.lower() or kw.lower() in sequencing_kit.lower():
				self.cmd.append('-b')
				break
		self.cmd.append('-l')
		if 'rna' in experiment.lower() or 'rna' in sequencing_kit.lower():
			self.cmd.append(str(min_length_rna))
		else:
			self.cmd.append(str(min_length))
		self.cmd.append(os.path.join(data_basedir, relative_path, ''))
		self.process = None

	def run(self):
		self.logger.info("STARTED watchnchop scheduler")
		while not (self.stoprequest.is_set() or self.exp_end.is_set()):
			if self.conditions_met():
				self.process = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.IDLE_PRIORITY_CLASS)
				self.logger.info("STARTED WATCHNCHOP with arguments: {}".format(self.cmd))
				break
			time.sleep(1)
		while not (self.stoprequest.is_set() or self.exp_end.is_set()):
			time.sleep(1)
		if self.process:
			try:
				self.process.terminate()
				self.logger.info("TERMINATED watchnchop process")
			except:
				self.logger.error("TERMINATING watchnchop process failed")
		else:
			if self.stoprequest.is_set():
				self.logger.error("watchnchop was NEVER STARTED: this thread was ordered to kill the watchnchop subprocess before it was started")
				return
			
			# try one last time to start watchnchop (necessary for runs with extremly low output, where all reads are buffered)
			self.logger.info("starting watchnchop in one minutes, then kill it after another 5 minutes")
			for i in range(60):
				if self.stoprequest.is_set():
					self.logger.error("watchnchop was NEVER STARTED: this thread was ordered to kill the watchnchop subprocess before it was started")
					return
				time.sleep(1)
			if self.conditions_met():
				self.process = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.IDLE_PRIORITY_CLASS)
				self.logger.info("STARTED WATCHNCHOP with arguments: {}".format(self.cmd))
			else:
				self.logger.error("watchnchop NOT STARTED: directory {} still does not exist or contains no fastq files".format(self.observed_dir))
				return
			for i in range(300):
				if self.stoprequest.is_set():
					break
				time.sleep(1)
			self.process.terminate()
			self.logger.info("TERMINATED watchnchop process")

	def conditions_met(self):
		if os.path.exists(self.observed_dir):
			if [fn for fn in os.listdir(self.observed_dir) if fn.endswith('.fastq')]:
				return True
		return False

	def join(self, timeout=None):
		if timeout:
			self.exp_end.set()
		else:
			self.stoprequest.set()
		super(WatchnchopScheduler, self).join(timeout)


class StatsparserScheduler(threading.Thread):

	def __init__(self, update_interval, sample_dir, statsparser_args, channel):
		threading.Thread.__init__(self)
		if getattr(self, 'daemon', None) is None:
			self.daemon = True
		else:
			self.setDaemon(True)
		self.stoprequest = threading.Event()	# set when joined without timeout (eg if terminated with ctr-c)
		self.exp_end = threading.Event()		# set when joined with timeout (eg if experiment ended)
		self.logger = logging.getLogger(name='gw.w{}.sps'.format(channel+1))
		self.channel = channel

		self.update_interval = update_interval
		self.sample_dir = sample_dir
		self.statsparser_args = statsparser_args
		self.page_opened = False

	def run(self):
		while not self.stoprequest.is_set() or self.exp_end.is_set():
			last_time = time.time()

			if self.conditions_met():
				self.update_report()

			this_time = time.time()
			while (this_time - last_time < self.update_interval) and not self.stoprequest.is_set() or self.exp_end.is_set():
				time.sleep(1)
				this_time = time.time()
		# start statsparser a last time if the experiment ended
		if not self.stoprequest.is_set() and self.conditions_met():
			self.update_report()

		SP_DIRS_LOCK.acquire()
		if self.sample_dir in SP_DIRS:
			if SP_DIRS[self.sample_dir] == self.channel:
				del SP_DIRS[self.sample_dir]
		SP_DIRS_LOCK.release()

	def conditions_met(self):
		conditions_met = False
		stats_fns = [fn for fn in os.listdir(os.path.abspath(self.sample_dir)) if fn.endswith('stats.csv')] if os.path.exists(os.path.abspath(self.sample_dir)) else []
		# assure that only one statsparser instance is running on a directory at a time
		SP_DIRS_LOCK.acquire()
		if not self.sample_dir in SP_DIRS:
			SP_DIRS[self.sample_dir] = self.channel
		if stats_fns and SP_DIRS[self.sample_dir] == self.channel:
			conditions_met = True
		SP_DIRS_LOCK.release()
		return conditions_met

	def update_report(self):
		self.logger.info("updating report...")
		cmd = [os.path.join(get_script_dir(),'statsparser'), #TODO: change to which() ?
			   self.sample_dir,
			   '-q']
		cmd.extend(self.statsparser_args)
		cp = subprocess.run(cmd) # waits for process to complete
		if cp.returncode == 0:
			if not self.page_opened:
				basedir = os.path.abspath(self.sample_dir)
				fp = os.path.join(basedir, 'report.html')
				self.logger.info("OPENING " + fp)
				try:
					webbrowser.open('file://' + os.path.realpath(fp))
				except:
					pass
				self.page_opened = True
		else:
			self.logger.warning("statsparser returned with errorcode {} for directory {}".format(cp.returncode, self.sample_dir))

	def join(self, timeout=None):
		if timeout:
			self.exp_end.set()
		else:
			self.stoprequest.set()
		super(StatsparserScheduler, self).join(timeout)


class Watcher():

	def __init__(self, minknow_log_basedir, channel, ignore_file_modifications, output_dir, data_basedir, 
				 statsparser_args, update_interval, watchnchop_args, min_length, min_length_rna, bc_kws):
		self.q = queue.PriorityQueue()
		self.watchnchop_args = watchnchop_args
		self.min_length = min_length
		self.min_length_rna = min_length_rna
		self.channel = channel
		self.output_dir = output_dir
		self.data_basedir = data_basedir
		self.statsparser_args = statsparser_args
		self.update_interval = update_interval
		self.bc_kws = bc_kws
		self.observed_dir = os.path.join(minknow_log_basedir, "GA{}0000".format(channel+1))
		self.event_handler = LogFilesEventHandler(self.q, ignore_file_modifications, channel)
		self.observer = Observer()
		self.observer.schedule(self.event_handler, 
							   self.observed_dir, 
							   recursive=False)
		self.observer.start()
		self.channel_status = ChannelStatus("GA{}0000".format(channel+1), channel)
		self.spScheduler = None
		self.wcScheduler = []
		self.logger = logging.getLogger(name='gw.w{}'.format(channel+1))

		self.logger.info("...watcher for {} ready".format(self.observed_dir))

	def check_q(self):
		# checking sheduler queue
		if not self.q.empty():
			self.logger.debug("Queue content for {}:".format(self.observed_dir))
		while not self.q.empty():
			timestamp, origin, line = self.q.get()
			self.logger.debug("received '{}' originating from '{} log' at '{}'".format(line, origin, timestamp))

			if origin == 'server':
				self.parse_server_log_line(line)
			elif origin == 'bream':
				self.parse_bream_log_line(line)
			#elif origin == 'analyser':
			#	self.parse_analyser_log_line(line)

	def parse_server_log_line(self, line):
		dict_content = {}
		overwrite = False
		timestamp = line[:23]

		# fetch output_path, run_id, script_path, relative_path, protocol_start, flowcell_id [, experiment, sample]
		if   	"protocol_started"										in line:
			for m in re.finditer('([^\s,]+) = ([^\s,]+)', line):
				dict_content[m.group(1)] = m.group(2)
			overwrite = True
			dict_content['relative_path'] = dict_content['output_path'].split("/./")[1].strip("/")
			subdirs = dict_content['relative_path'].split('/')
			if len(subdirs) == 3:
				# case sequencing protocol
				dict_content['experiment'] = subdirs[0]
				dict_content['sample'] = subdirs[1]
				dict_content['flowcell_id'] = subdirs[2].split('_')[3]
			elif len(subdirs) == 1:
				# case qc protocol
				dict_content['flowcell_id'] = subdirs[0].split('_')[3]
			self.logger.info("PROTOCOL START")
			set_update_overview()
			self.channel_status.run_data['protocol_start'] = timestamp

		# fetch protocol_end
		elif	"protocol_finished" 									in line:
			self.logger.info("PROTOCOL END")
			set_update_overview()
			self.channel_status.run_data['protocol_end'] = timestamp
			if self.channel_status.mux_scans:
				self.save_logdata()
			self.channel_status.reset_channel()
			self.stop_statsparser()
			self.stop_watchnchop()

		# 
		elif	"[engine/info]: : flowcell_discovered" 					in line:
			for m in re.finditer('([^\s,]+) = ([^\s,]+)', line):
				dict_content[m.group(1)] = m.group(2)
			overwrite = True
			self.logger.info("FLOWCELL DISCOVERED")
			set_update_overview()
			self.channel_status.flowcell_disconnected()
			self.stop_statsparser()
			self.stop_watchnchop()

		elif   	"[engine/info]: : data_acquisition_started"				in line:
			for m in re.finditer('([^\s,]+) = ([^\s,]+)', line):
				dict_content[m.group(1)] = m.group(2)
			overwrite = True

		elif	"flowcell_disconnected"									in line:
			self.logger.info("FLOWCELL DISCONNECTED")
			set_update_overview()
			self.channel_status.flowcell_disconnected()

		elif 	"pores available for sequencing" 						in line:
			active_pores = None
			in_use = None
			for m in re.finditer("has ([0-9]+) pores available for sequencing", line):
				active_pores = m.group(1)
			for m in re.finditer("Starting sequencing with ([0-9]+) pores", line):
				in_use = m.group(1)
			self.logger.info("new mux scan result: {} active, {} in use".format(active_pores, in_use))
			self.channel_status.add_mux_scan(timestamp, active_pores, in_use=in_use)
			set_update_overview()
			self.save_logdata()

		if dict_content:
			self.channel_status.update(dict_content, overwrite)

	def parse_bream_log_line(self, line):
		dict_content = {}
		overwrite = False
		timestamp = line.split(" - ")[1]

		if 		"INFO - Attribute"								in line:
			for m in re.finditer("([^\s,]+) set to (.+)", line): 
				dict_content[m.group(1)] = m.group(2)

		elif 	"INFO - Asked to start protocol"				in line:
			for m in re.finditer("'--([^\s,]+)=([^\s,]+)'", line):
				dict_content[m.group(1)] = m.group(2)
				overwrite = True

		elif 	"INFO - Updating context tags in MinKNOW with" 	in line:
			for m in re.finditer("'([^\s,]+)'[:,] u?'([^\s,]+)'", line):
				dict_content[m.group(1)] = m.group(2)
			if 'sequencing_kit' in dict_content:
				dict_content['sequencing_kit'] = dict_content['sequencing_kit'].upper()

		elif	"platform_qc.report"			in line:
			self.logger.info("QC FINISHED")

		elif	"sequencing.start"										in line:
			dict_content["sequencing_start_time"] = timestamp
			self.logger.info("SEQUENCING STARTS")
			self.channel_status.sequencing = True
			set_update_overview()

			self.start_watchnchop()
			self.start_statsparser()

		if dict_content:
			self.channel_status.update(dict_content, overwrite)

	def check_attributes(self, attributes):
		for key in attributes:
			if key in self.channel_status.run_data:
				if self.channel_status.run_data[key]:
					continue
				else:
					return key
			elif key in self.channel_status.flowcell:
				if self.channel_status.flowcell[key]:
					continue
				else:
					return key
			else:
				return key
		return None


	def save_logdata(self):
		missing_key = self.check_attributes(['experiment_type', 'run_id', 'flowcell_id', 'asic_id_eeprom'])
		if missing_key:
			self.logger.warning("NOT SAVING REPORT for {} because the crucial attribute '{}' is missing".format(self.channel_status.run_data['run_id'], missing_key))
			return

		fn = []
		if "qc" in self.channel_status.run_data['experiment_type'].lower():
			missing_key = self.check_attributes(['experiment', 'sample'])
			if not missing_key:
				self.logger.warning("NOT SAVING REPORT for {} because it is not certain that this is a qc run".format(self.channel_status.run_data['run_id']))
				return
			fn.extend(["QC", self.channel_status.flowcell['flowcell_id'], self.channel_status.run_data['run_id']])
			target_dir = os.path.join(self.output_dir, 'qc')
		else:
			missing_key = self.check_attributes(['experiment', 'sample'])
			if missing_key:
				self.logger.warning("NOT SAVING REPORT for {} because the crucial attribute '{}' is missing".format(self.channel_status.run_data['run_id'], missing_key))
				return
			fn.extend([self.channel_status.run_data['run_id'], 'logdata'])
			target_dir = os.path.join(self.output_dir,
									  'runs', 
									  self.channel_status.run_data['experiment'], 
									  self.channel_status.run_data['sample'])
		fn = "_".join(fn) + ".json"

		self.logger.info("saving log data to file {}".format(os.path.join(target_dir, fn)))
		data = (self.channel_status.flowcell, self.channel_status.run_data, self.channel_status.mux_scans)
		if not os.path.exists(target_dir):
			os.makedirs(target_dir)
		with open( os.path.join(target_dir, fn), 'w') as f:
			print(json.dumps(data, indent=4), file=f)

		ALL_RUNS_LOCK.acquire()
		run_id = self.channel_status.run_data['run_id']
		asic_id_eeprom = self.channel_status.flowcell['asic_id_eeprom']
		if asic_id_eeprom in ALL_RUNS:
			ALL_RUNS[asic_id_eeprom][run_id] = {'flowcell': data[0],
												'run_data': data[1],
												'mux_scans': data[2]}
		else:
			ALL_RUNS[asic_id_eeprom] = {}
			ALL_RUNS[asic_id_eeprom][run_id] = {'flowcell': data[0],
												'run_data': data[1],
												'mux_scans': data[2]}
		ALL_RUNS_LOCK.release()

	def start_watchnchop(self):
		missing_key = self.check_attributes(['experiment', 'sample', 'sequencing_kit', 'run_id', 'fastq_reads_per_file', 'relative_path'])
		if missing_key:
			self.logger.warning("NOT executing watchnchop because the crucial attribute '{}' is missing".format(missing_key))
			return

		self.stop_watchnchop()

		stats_fp = os.path.join(self.output_dir,
								'runs',
								self.channel_status.run_data['experiment'],
								self.channel_status.run_data['sample'],
								"{}_stats.csv".format(self.channel_status.run_data['run_id']))
		self.wcScheduler.append(WatchnchopScheduler(self.data_basedir,
													self.channel_status.run_data['relative_path'],
													self.channel_status.run_data['experiment'],
													self.channel_status.run_data['sequencing_kit'],
													self.channel_status.run_data['fastq_reads_per_file'],
													self.bc_kws,
													stats_fp,
													self.channel,
													self.watchnchop_args,
													self.min_length,
													self.min_length_rna))
		self.wcScheduler[-1].start()
		return

	def stop_watchnchop(self, timeout=1.2):
		if self.wcScheduler[-1].is_alive() if self.wcScheduler else None:
			if timeout:
				self.wcScheduler[-1].join(timeout)
			else:
				self.wcScheduler[-1].join()

	def start_statsparser(self):
		missing_key = self.check_attributes(['experiment', 'sample'])
		if missing_key:
			self.logger.warning("NOT starting statsparser scheduler because the crucial attribute '{}' is missing".format(missing_key))
			return

		#start creation of plots at regular time intervals
		self.stop_statsparser()
		sample_dir = os.path.join(self.output_dir,
								  'runs',
								  self.channel_status.run_data['experiment'],
								  self.channel_status.run_data['sample'])
		self.logger.info('SCHEDULING update of report for sample {1} every {0:.1f} minutes'.format(self.update_interval/1000, sample_dir))
		self.spScheduler = StatsparserScheduler(self.update_interval, 
												sample_dir, 
												self.statsparser_args, 
												self.channel)
		self.spScheduler.start()

	def stop_statsparser(self, timeout=1.2):
		if self.spScheduler.is_alive() if self.spScheduler else None:
			if timeout:
				self.spScheduler.join(timeout)
			else:
				self.spScheduler.join()

class OpenedFilesHandler():
	'''manages a set of opened files, reads their contents and 
	processes them line by line. Incomplete lines are stored until
	they are "completed" by a newline character.'''
	def __init__(self, channel):
		self.logger = logging.getLogger(name='gw.w{}.ofh'.format(channel+1))
		self.open_files = {}

	def open_new_file(self, path):
		self.logger.info("Opening file {}".format(path))
		self.open_files[path] = [open(path, 'r'), ""]

	def close_file(self, path):
		self.logger.debug("Attempting to close file {}".format(path))
		try:
			self.open_files[path][0].close()
		except:
			self.logger.debug("File handle of file {} couldn't be closed".format(path))
		if path in self.open_files:
			del self.open_files[path]
			self.logger.debug("Deleted entry in open_files for file {}".format(path))

	def process_lines_until_EOF(self, process_function, path):
		file = self.open_files[path][0]
		while 1:
			line = file.readline()
			if line == "":
				break
			elif line.endswith("\n"):
				line = (self.open_files[path][1] + line).strip()
				if line:
					process_function(line)
				self.open_files[path][1] = ""
			else:
				#line potentially incomplete
				self.open_files[path][1] = self.open_files[path][1] + line


class LogFilesEventHandler(FileSystemEventHandler):
	control_server_log, bream_log = None, None

	def __init__(self, q, ignore_file_modifications, channel):
		super(LogFilesEventHandler, self).__init__()
		self.ignore_file_modifications = ignore_file_modifications
		self.file_handler = OpenedFilesHandler(channel)
		self.comm_q = q

		# while no server log file is opened, all lines read are buffered in a seperate Priority Queue
		self.buff_q = queue.PriorityQueue()
		self.q = self.buff_q
		self.logger = logging.getLogger(name='gw.w{}.lfeh'.format(channel+1))

	def on_moved(self, event):
		pass

	def on_created(self, event):
		if not event.is_directory:
			activate_q = False
			self.logger.debug("File {} was created".format(event.src_path))
			basename = os.path.basename(event.src_path)
			if basename.startswith("control_server_log"):
				if self.control_server_log:
					self.file_handler.close_file(event.src_path)
					self.logger.info("Replacing current control_server_log file {} with {}".format(self.control_server_log, event.src_path))
				else:
					# read lines of server file first, then activate the real communication q
					activate_q = True
				self.control_server_log = event.src_path
				self.logger.info("New control_server_log file {}".format(self.control_server_log))
				process_function = self.enqueue_server_log_line
			elif basename.startswith("bream") and basename.endswith(".log"):
				if self.bream_log:
					self.file_handler.close_file(event.src_path)
					self.logger.info("Replacing current bream_log file {} with {}".format(self.bream_log, event.src_path))
				self.bream_log = event.src_path
				self.logger.info("New bream_log file {}".format(self.bream_log))
				process_function = self.enqueue_bream_log_line
			else:
				self.logger.debug("File {} is not of concern for this tool".format(event.src_path))
				return
			self.file_handler.open_new_file(event.src_path)
			self.file_handler.process_lines_until_EOF(process_function, event.src_path)
			self.logger.info("approx. queue size: {}".format(self.q.qsize()))
			if activate_q:
				self.activate_q()

	def on_deleted(self, event):
		if not event.is_directory:
			self.logger.debug("File {} was deleted".format(event.src_path))
			#self.file_handler.close_file(event.src_path)
			if self.control_server_log == event.src_path:
				control_server_log = None
				self.logger.warning("Current control_server_log file {} was deleted!".format(event.src_path))
			elif self.bream_log == event.src_path:
				self.bream_log = None
				self.logger.warning("Current bream_log file {} was deleted".format(event.src_path))
			else:
				self.logger.debug("File {} is not opened and is therefore not closed.".format(event.src_path))
			self.file_handler.close_file(event.src_path)

	def on_modified(self, event):
		if not event.is_directory:
			self.logger.debug("File {} was modified".format(event.src_path))
			if event.src_path in self.file_handler.open_files:
				if self.control_server_log == event.src_path:
					self.file_handler.process_lines_until_EOF(self.enqueue_server_log_line, event.src_path)
				elif self.bream_log == event.src_path:
					self.file_handler.process_lines_until_EOF(self.enqueue_bream_log_line, event.src_path)
				else:
					self.logger.warning("case not handled")
					return
			else:
				if not self.ignore_file_modifications:
					self.on_created(event)
				else:
					self.logger.debug("File {} existed before this script was started".format(event.src_path))

	def activate_q(self):
		self.logger.info("activating communication queue")
		self.q = self.comm_q
		while not self.buff_q.empty():
			self.q.put(self.buff_q.get())

	def enqueue_server_log_line(self, line):
		try:
			self.q.put( (dateutil.parser.parse(line[:23]), 'server', line) )
		except:
			self.logger.debug("the timestamp of the following line in the server log file could not be parsed:\n{}".format(line))

	def enqueue_bream_log_line(self, line):
		try:
			self.q.put( (dateutil.parser.parse(line.split(' - ')[1]), 'bream', line) )
		except:
			self.logger.debug("the timestamp of the following line in the bream log file could not be parsed:\n{}".format(line))


class RunsDirsEventHandler(FileSystemEventHandler):

	def __init__(self, observed_dir):
		super(RunsDirsEventHandler, self).__init__()
		self.observed_dir = os.path.abspath(observed_dir)
		self.logger = logging.getLogger(name='gw.reh')

	def on_moved(self, event):
		if event.is_directory or (self.depth(event.src_path) == 3 and event.src_path.endswith('.json')):
			self.logger.debug("moved {}, depth {}, \ndest {}".format(event.src_path, self.depth(event.src_path), event.dest_path))
			if self.observed_dir in event.dest_path and self.depth(event.dest_path) == self.depth(event.src_path):
				self.reload_runs()
			else:
				self.on_deleted(event)

	def on_created(self, event):
		if event.is_directory:
			self.logger.debug("created directory {}, depth {}".format(event.src_path, self.depth(event.src_path)))
			if 1 <= self.depth(event.src_path) <= 2:
				self.reload_runs()
		elif self.depth(event.src_path) == 3 and event.src_path.endswith('.json'):
			self.logger.debug("created file {}, depth {}".format(event.src_path, self.depth(event.src_path)))
			self.reload_runs()

	def on_modified(self, event):
		if event.is_directory:
			self.logger.debug("modified directory {}, depth {}".format(event.src_path, self.depth(event.src_path)))

	def on_deleted(self, event):
		if event.is_directory:
			self.logger.debug("deleted directory {}, depth {}".format(event.src_path, self.depth(event.src_path)))
			if 1 <= self.depth(event.src_path) <= 2:
				self.reload_runs()
		elif self.depth(event.src_path) == 3 and event.src_path.endswith('.json'):
			self.logger.debug("deleted file {}, depth {}".format(event.src_path, self.depth(event.src_path)))
			self.reload_runs()

	def depth(self, src_path):
		src_path = os.path.abspath(src_path)
		return len(src_path.replace(self.observed_dir, '').strip('/').split('/'))

	def reload_runs(self):
		ALL_RUNS_LOCK.acquire()
		self.logger.info('deleting and re-importing all runs due to changes in the run directory')
		# delete sequencing runs
		to_delete = []
		for asic_id_eeprom in ALL_RUNS:
			for run_id in ALL_RUNS[asic_id_eeprom]:
				if 'qc' not in ALL_RUNS[asic_id_eeprom][run_id]['run_data']['experiment_type']:
					to_delete.append( (asic_id_eeprom, run_id) )
		for asic_id_eeprom, run_id in to_delete:
			del ALL_RUNS[asic_id_eeprom][run_id]
		#reload runs
		import_runs(self.observed_dir)
		ALL_RUNS_LOCK.release()
		set_update_overview()
		return

def standalone():
	args = parse_args()
	main(args)

if __name__ == "__main__":
	standalone()
