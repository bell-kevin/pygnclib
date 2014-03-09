#!/usr/bin/env python
#
# This file is part of the pygnclib project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import sys, gzip, uuid, re
import pyxb, argparse

import gnucash, gnc, trn, cmdty, ts, split   # Bindings generated by PyXB
from datetime import date, datetime

# meh, for export, have to manually declare namespace prefixes
import cd
import _nsgroup as ns
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_act, 'act')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_addr, 'addr')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_bgt, 'bgt')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_billterm, 'billterm')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_book, 'book')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_bt_days, 'bt-days')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_bt_prox, 'bt-prox')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(cd.Namespace, 'cd')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_cmdty, 'cmdty')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_cust, 'cust')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_employee, 'employee')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_gnc, 'gnc')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_invoice, 'invoice')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_job, 'job')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_lot, 'lot')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_order, 'order')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_owner, 'owner')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_price, 'price')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_recurrence, 'recurrence')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_slot, 'slot')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_split, 'split')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_sx, 'sx')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_taxtable, 'taxtable')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_trn, 'trn')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ts.Namespace, 'ts')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_tte, 'tte')
pyxb.utils.domutils.BindingDOMSupport.DeclareNamespace(ns._Namespace_vendor, 'vendor')

# lookup account with given name in dict (or search in xml tree)
def lookupAccountUUID(xml_tree, account_name):
    for elem in xml_tree:
        # get account with matching name (partial match is ok)
        if elem.name.find(account_name) != -1:
            accounts[account_name] = elem.id.value()
            return elem.id.value()

    print "Did not find account with name %s in current book, bailing out!" % account_name
    exit(1)

# main script
parser = argparse.ArgumentParser(description="Prune certain transactions",
                                 epilog="Delete transactions in one account, matching certain criteria. "
                                        "Give one or more instances of -d or -m, with the latter supporting the "
                                        "following syntax: Python regexp are permitted, with each group being matched "
                                        "against corresponding other matches'. Example: '.*txn id: (\W+).*'. Transactions "
                                        "with matching corresponding group content (in this case: same transaction ids) "
                                        "will have all but the newest transaction removed. If you need to prune *all* "
                                        "transactions of a certain kind, leave out the grouping. Example: '.*withdrawal.*' "
                                        "will remove *all* matching withdrawal transactions.")
parser.add_argument("-v", "--verbosity", action="count", default=0, help="Increase verbosity by one (defaults to off)")
parser.add_argument("-p", "--pretty", action="store_true", default=False, help="Export xml pretty-printed (defaults to off)")
parser.add_argument("-a", "--account", action="append", help="Account names to match")
parser.add_argument("-d", "--date", action="append", help="Date range, e.g. 2012-01-01..2012-02-01, or 2012-01-01..")
parser.add_argument("-m", "--match", action="append", help="Template string for description to match. Can be regexp. Use "
                                                           "grouping to request dupe removals.")
parser.add_argument("ledger_gnucash", help="GnuCash ledger you want to import into")
parser.add_argument("output_gnucash", help="Output GnuCash ledger file")
args = parser.parse_args()

gncfile = args.ledger_gnucash
outfile = args.output_gnucash

if args.verbosity > 0: print "Opening gnc file"

# read GnuCash data
try:
    f = gzip.open(gncfile)
    gncxml = f.read()
except:
    f = open(gncfile)
    gncxml = f.read()

if args.verbosity > 0: print "Parsing gnc file"

try:
    doc = gnucash.CreateFromDocument(
        gncxml,
        location_base=gncfile)
except pyxb.UnrecognizedContentError as e:
    print '*** ERROR validating input:'
    print 'Unrecognized element "%s" at %s (details: %s)' % (e.content.expanded_name, e.content.location, e.details())
except pyxb.UnrecognizedDOMRootNodeError as e:
    print '*** ERROR matching content:'
    print e.details()

if args.verbosity > 0: print "Attempting delete over %d transactions..." % len(doc.book.transaction)

# fill uuids of accounts we want to match
accounts = {}
if args.account:
    for acc in args.account:
        account_uuid = lookupAccountUUID(doc.book.account, acc)
        accounts[account_uuid] = True

# fill date predicates of dates we want to match
dates = []
if args.date:
    for dt in args.date:
        dt_range = str.split(dt, "..")
        if dt_range is None or len(dt_range) != 2:
            print "Invalid date predicate given: "+dt
            exit(1)
        if dt_range[0] == '':
            upper=datetime.strptime(dt_range[1], '%Y-%m-%d')
            dates.append( lambda x, upper=upper: x <= upper )
        elif dt_range[1] == '':
            lower=datetime.strptime(dt_range[0], '%Y-%m-%d')
            dates.append( lambda x, lower=lower: lower <= x)
        else:
            lower=datetime.strptime(dt_range[0], '%Y-%m-%d')
            upper=datetime.strptime(dt_range[1], '%Y-%m-%d')
            dates.append( lambda x, lower=lower, upper=upper: lower <= x <= upper )

# fill compiled regexs we want memo / desc strings to match against
regexps = []
if args.match:
    regexps = [ re.compile(x) for x in args.match ]

# go through all Txn (backwards, to make inplace deletion not screw
# up iterator)
matches = {}
for index in range(len(doc.book.transaction) - 1, -1, -1):
    txn = doc.book.transaction[index]
    match = False
    if len(accounts):
        for split in txn.splits.split:
            if accounts.has_key( split.account.value() ):
                match = True
                break
        if not match:
            continue

    match = False
    if len(dates):
        for pred in dates:
            if pred( datetime.strptime(
                    str.split(str(txn.date_posted.date), ' +')[0], '%Y-%m-%d %H:%M:%S') ):
                match = True
                break
        if not match:
            continue

    match = False
    if len(regexps):
        key = ""
        for exp in regexps:
            m0 = exp.match( txn.description if txn.description else "" )
            if m0 is not None:
                match = True
                key = "".join(m0.groups())
                break
            for split in txn.splits.split:
                m1 = exp.match( split.memo if split.memo else "" )
                if m1 is not None:
                    match = True
                    key = "".join(m1.groups())
                    break
        if not match:
            continue

        # dupe removal case? empty key otherwise means 'remove all
        # matches'
        if len(key) > 0:
            if not key in matches:
                # new encounter, stick into dict, do *not* remove
                matches[key] = True
                continue

    if args.verbosity > 0: print "Deleting txn %s" % txn.description
    del doc.book.transaction[index]

if args.verbosity > 0: print "Writing resulting ledger"

# write out amended ledger
out = open(outfile, "wb")
if args.pretty:
    dom = doc.toDOM()
    out.write( dom.toprettyxml(indent=" ", encoding='utf-8') )
else:
    out.write( doc.toxml(encoding='utf-8') )
