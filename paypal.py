#!/usr/bin/env python
#
# This file is part of the pygnclib project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import sys, gzip, uuid, re
import pyxb, csv, argparse

import gnucash, gnc, trn, cmdty, ts, split   # Bindings generated by PyXB
from datetime import date, datetime
from fractions import Fraction
from currency import CurrencyConverter

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

def getGNCDateStr(date_obj):
    return date_obj.strftime('%Y-%m-%d %H:%M:%S +0100')

class InputLine:
    def __init__(self, line):
        # remove crap, encode into unicode
        name = re.sub(r"[\x01-\x1F\x7F]", "", line[" Name"])
        self.name = name.decode(args.encoding)
        self.transaction_date = datetime.strptime(
            line["Date"] + " " + line[" Time"],
            '%d.%m.%Y %H:%M:%S')
        self.transaction_type = line[" Type"]
        self.transaction_state = line[" Status"]
        self.transaction_currency = line[" Currency"]
        self.transaction_gross = line[" Gross"]
        self.transaction_fee = line[" Fee"]
        self.transaction_net = line[" Net"]
        self.transaction_id  = line[" Transaction ID"]
        self.reference_txn = line[" Reference Txn ID"]
    def __str__(self):
        return "%s %s %s %s %s %s %s %s %s" % (getGNCDateStr(self.transaction_date),
                                               self.transaction_type,
                                               self.transaction_state,
                                               self.transaction_currency,
                                               self.transaction_gross,
                                               self.transaction_fee,
                                               self.transaction_net,
                                               self.transaction_id,
                                               self.reference_txn)

# convert float from paypal number string
def amountFromPayPal(value):
    # assume German locale here for the while
    minusIdx = value.find("-")
    preMult  = 1
    if minusIdx != -1:
        value = value[minusIdx+1:]
        preMult  = -1
    # kill all thousands separators, split off fractional part
    value_parts = value.replace(".","").split(',')
    if len(value_parts) == 1:
        return preMult * float(value_parts[0])
    if len(value_parts) == 2:
        return preMult * (float(value_parts[0]) + float(value_parts[1])/(10**len(value_parts[1])))
    else:
        raise IndexError

# convert number to integer string (possibly via conversion to rational number)
def gnucashFromAmount(value):
    rational_value = Fraction(value).limit_denominator(1000)
    return str(rational_value.numerator)+"/"+str(rational_value.denominator)

class PayPalConverter:
    def __init__(self, book, args):
        # enter current time as "date entered"
        self.now = datetime.now().strftime('%Y-%m-%d %H:%M:%S +0100')
        self.acc_lookup = {}
        self.document = book
        self.accounts = book.account
        self.default_currency = args.currency
        self.currency_converter = CurrencyConverter(verbosity=args.verbosity)

    # wrap the converter here, to be able to convert value to float if
    # necessary
    def currencyConvert(self, value, currency, txn_date):
        if isinstance(value, str):
            value = amountFromPayPal(value)
        return self.currency_converter.convert(value, currency, args.currency, txn_date)

    # lookup account with given name (and optionally type) in dict (or
    # search in xml tree)
    def lookupAccountUUID(self, account_name, **kwargs):
        acc_type = kwargs.pop('type', '')
        lookup_key = acc_type+account_name

        if self.acc_lookup.has_key(lookup_key):
            return self.acc_lookup[lookup_key]
        else:
            for elem in self.accounts:
                # get account with matching name and type (partial match is ok)
                if elem.name.find(account_name) != -1 and elem.type.find(acc_type) != -1:
                    self.acc_lookup[lookup_key] = elem.id.value()
                    return elem.id.value()
        print "Did not find account with name %s in current book, bailing out!" % account_name
        exit(1)

    # add a gnucash split transaction with the given data
    def addTransaction(self, transaction_date,
                       account1_name, account1_memo,
                       account2_name, account2_memo,
                       transaction_currency, transaction_value, transaction_description):
        if isinstance(transaction_value, str):
            transaction_value = amountFromPayPal(transaction_value)

        # don't accept non-default currencies here. users need to use
        # addMultiCurrencyTransaction for that
        if self.default_currency != transaction_currency and transaction_value != 0:
            print "Wrong currency for main transaction encountered, bailing out!"
            if args.verbosity > 0: print "Context: "+str(currLine)
            exit(1)

        try:
            account1_uuid = self.lookupAccountUUID(account1_name)
            account2_uuid = self.lookupAccountUUID(account2_name)

            # create a new transaction with two splits - just lovely this
            # pyxb design - the below is written by _just_ looking at the
            # rng schema
            self.document.append(
                gnc.transaction(
                    trn.id( uuid.uuid4().hex, type="guid" ),
                    trn.currency( cmdty.space("ISO4217"), cmdty.id(transaction_currency) ),
                    trn.date_posted( ts.date(getGNCDateStr(transaction_date)) ),
                    trn.date_entered( ts.date(self.now) ),
                    trn.description(transaction_description),
                    trn.splits(
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account1_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(transaction_value) ),
                            split.quantity( gnucashFromAmount(transaction_value) ),
                            split.account( account1_uuid, type="guid" )),
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account2_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(-transaction_value) ),
                            split.quantity( gnucashFromAmount(-transaction_value) ),
                            split.account( account2_uuid, type="guid" ))),
                    version="2.0.0" ))
        except pyxb.UnrecognizedContentError as e:
            print '*** ERROR validating input:'
            print 'Unrecognized element "%s" at %s (details: %s)' % (e.content.expanded_name,
                                                                     e.content.location, e.details())

    # add a gnucash multi-currency split transaction with the given data
    def addMultiCurrencyTransaction(self, transaction_date,
                                    transaction_currency1, currency1_account_name,
                                    transaction_currency2, currency2_account_name,
                                    transaction_value_currency1,
                                    transaction_value_currency2,
                                    account1_name, account1_memo,
                                    account2_name, account2_memo,
                                    transaction_description):
        try:
            account1_uuid = self.lookupAccountUUID(account1_name)
            account2_uuid = self.lookupAccountUUID(account2_name)
            currency1_account_uuid = self.lookupAccountUUID(currency1_account_name, type='TRADING')
            currency2_account_uuid = self.lookupAccountUUID(currency2_account_name, type='TRADING')

            # if necessary convert values to float first
            if isinstance(transaction_value_currency1, str):
                transaction_value_currency1 = amountFromPayPal(transaction_value_currency1)
            if isinstance(transaction_value_currency2, str):
                transaction_value_currency2 = amountFromPayPal(transaction_value_currency2)

            # create a new transaction with four splits - just lovely this
            # pyxb design - the below is written by _just_ looking at the
            # rng schema
            self.document.append(
                gnc.transaction(
                    trn.id( uuid.uuid4().hex, type="guid" ),
                    trn.currency( cmdty.space("ISO4217"), cmdty.id(transaction_currency1) ),
                    trn.date_posted( ts.date(getGNCDateStr(transaction_date)) ),
                    trn.date_entered( ts.date(self.now) ),
                    trn.description(transaction_description),
                    trn.splits(
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account1_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(transaction_value_currency1) ),
                            split.quantity( gnucashFromAmount(transaction_value_currency1) ),
                            split.account( account1_uuid, type="guid" )),
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account1_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(-transaction_value_currency1) ),
                            split.quantity( gnucashFromAmount(-transaction_value_currency1) ),
                            split.account( currency1_account_uuid, type="guid" )),
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account2_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(-transaction_value_currency2) ),
                            split.quantity( gnucashFromAmount(-transaction_value_currency2) ),
                            split.account( account2_uuid, type="guid" )),
                        trn.split(
                            split.id( uuid.uuid4().hex, type="guid" ),
                            split.memo( account2_memo ),
                            split.reconciled_state( "n" ),
                            split.value( gnucashFromAmount(transaction_value_currency2) ),
                            split.quantity( gnucashFromAmount(transaction_value_currency2) ),
                            split.account( currency2_account_uuid, type="guid" ))),
                    version="2.0.0" ))
        except pyxb.UnrecognizedContentError as e:
            print '*** ERROR validating input:'
            print 'Unrecognized element "%s" at %s (details: %s)' % (e.content.expanded_name,
                                                                     e.content.location, e.details())

def default_importer(converter, **kwargs):
    currLine = kwargs.pop('line')

    converter.addTransaction(currLine.transaction_date,
                             'PayPal', "Unknown transaction",
                             'Imbalance', "Unknown PayPal",
                             currLine.transaction_currency, currLine.transaction_net,
                             "PayPal %s from %s - state: %s - ID: %s - gross: %s %s - fee: %s %s - net %s %s" % (
            currLine.transaction_type, currLine.name, currLine.transaction_state,
            currLine.transaction_id, currLine.transaction_currency,
            currLine.transaction_gross, currLine.transaction_currency,
            currLine.transaction_fee, currLine.transaction_currency,
            currLine.transaction_net))


# main script
parser = argparse.ArgumentParser(description="Import PayPal transactions from CSV",
                                 epilog="Extend this script by plugin snippets, that are simple python scripts with the following "
                                 "at the toplevel namespace (example):"
                                 "type_and_state = 'DonationsCompleted'"
                                 "def importer(PayPalConverter, **kwargs): converter.addTransaction(...)")
parser.add_argument("-v", "--verbosity", action="count", default=0, help="Increase verbosity by one (defaults to off)")
parser.add_argument("-p", "--pretty", action="store_true", default=False, help="Export xml pretty-printed (defaults to off)")
parser.add_argument("-d", "--delimiter", default='\t', help="Delimiter used in the CSV file  (defaults to tab)")
parser.add_argument("-q", "--quotechar", default='"', help="Quote character used in the CSV file (defaults to '\"')")
parser.add_argument("-e", "--encoding", default='iso-8859-1', help="Character encoding used in the CSV file (defaults to iso-8859-1)")
parser.add_argument("-c", "--currency", default="EUR", help="Currency all transactions are expected to be in (defaults to EUR)")
parser.add_argument("-s", "--script", action="append", help="Plugin snippets for sorting into different accounts")
parser.add_argument("ledger_gnucash", help="GnuCash ledger you want to import into")
parser.add_argument("paypal_csv", help="PayPal CSV export you want to import")
parser.add_argument("output_gnucash", help="Output GnuCash ledger file")
args = parser.parse_args()

gncfile = args.ledger_gnucash
csvfile = args.paypal_csv
outfile = args.output_gnucash

if args.verbosity > 0: print "Opening gnc file"

# read GnuCash data
try:
    f = gzip.open(gncfile)
    gncxml = f.read()
except:
    f = open(gncfile)
    gncxml = f.read()

# read paypal csv data
paypal_csv = csv.DictReader(open(csvfile), delimiter=args.delimiter, quotechar=args.quotechar)

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

conversion_scripts = {}
# import conversion scripts
if args.script:
    for index,script in enumerate(args.script):
        ns_name = "script"+str(index)
        exec "import "+script+" as "+ns_name
        conversion_scripts[eval(ns_name+".type_and_state")] = ns_name

if args.verbosity > 0: print "Importing CSV transactions"

converter = PayPalConverter(doc.book, args)
fwd_refs = {}
back_refs = {}
prev_line = None

for index,line in enumerate(paypal_csv):
    currLine = InputLine(line)

    # stick unmatched transactions into Imbalance account, in case we
    # don't find a handler below
    importer = default_importer

    # store txn id for potential back references
    back_refs[currLine.transaction_id] = currLine

    # find matching conversion script, if any
    if conversion_scripts.has_key(currLine.transaction_type+currLine.transaction_state):
        if eval(conversion_scripts[currLine.transaction_type+currLine.transaction_state]+".merge_nextline"):
            # store current line for _exactly_  one additional transaction
            if prev_line != None:
                print "Merge_nextline requested, but already pending line in line %d of %s, bailing out" % (index, args.paypal_csv)
                if args.verbosity > 0: print "Context: "+str(line)
                exit(1)
            prev_line = currLine
            continue # no further processing
        elif eval(conversion_scripts[currLine.transaction_type+currLine.transaction_state]+".store_fwdref"):
            # any backreferences to merge with?
            if back_refs.has_key(currLine.reference_txn):
                if back_refs[currLine.reference_txn].reference_txn == "":
                    print "Back reference without own forward reference, cannot merge after-the-fact line %d of %s, bailing out" % (index, args.paypal_csv)
                    if args.verbosity > 0: print "Context: "+str(line)
                    exit(1)
                # yup. gobble up prev line, if any
                if prev_line != None:
                    fwd_refs[back_refs[currLine.reference_txn].reference_txn].append(prev_line)
                    prev_line = None
                # and now append ourself to that one
                fwd_refs[back_refs[currLine.reference_txn].reference_txn].append(currLine)
                continue # no further processing

            if not fwd_refs.has_key(currLine.reference_txn):
                fwd_refs[currLine.reference_txn] = []

            # are we ourselves referenced? merge then. this joins up
            # chains of Txn references into one list, keeping only the
            # reference to the root transaction in the hash.
            if fwd_refs.has_key(currLine.transaction_id):
                fwd_refs[currLine.reference_txn].extend(fwd_refs[currLine.transaction_id])
                del fwd_refs[currLine.transaction_id]

            # gobble up prev line, if any
            if prev_line != None:
                fwd_refs[currLine.reference_txn].append(prev_line)
                prev_line = None

            fwd_refs[currLine.reference_txn].append(currLine)
            continue # no further processing
        elif eval(conversion_scripts[currLine.transaction_type+currLine.transaction_state]+".ignore"):
            if args.verbosity > 0: print "Ignoring transaction in line %d of %s" % (index, args.paypal_csv)
            continue # no further processing
        else:
            # now actually import transaction at hand
            importer = eval(conversion_scripts[currLine.transaction_type+currLine.transaction_state]+".importer")

    # run it
    if prev_line != None:
        if fwd_refs.has_key(currLine.transaction_id):
            print "Previous line merge done, but conflicting reference Txn found in line %d of %s, bailing out" % (index, args.paypal_csv)
            if args.verbosity > 0: print "Context: "+str(line)
            exit(1)

        # extra arg for previous line
        importer(converter, line=currLine, linenum=index, previous=prev_line, args=args)
        prev_line = None
    elif fwd_refs.has_key(currLine.transaction_id):
        # extra arg for list of reference txn
        importer(converter, line=currLine, linenum=index, previous=fwd_refs[currLine.transaction_id], args=args)
        del fwd_refs[currLine.transaction_id]
    else:
        # no extra args, just this one txn
        importer(converter, line=currLine, linenum=index, args=args)

# stick unmatched TxnReferences into imbalance account
for entry in fwd_refs.itervalues():
    for currLine in entry:
        default_importer(converter, line=currLine, linenum=-1, args=args)

# stick unused merge line into imbalance account
if prev_line != None:
    default_importer(doc.book, createTransaction, 'PayPal', 'Imbalance', line=prev_line, linenum=-1, args=args)

if args.verbosity > 0: print "Writing resulting ledger"

# write out amended ledger
out = open(outfile, "wb")
if args.pretty:
    dom = doc.toDOM()
    out.write( dom.toprettyxml(indent=" ", encoding='utf-8') )
else:
    out.write( doc.toxml(encoding='utf-8') )
