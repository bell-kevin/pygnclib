#!/usr/bin/env python
#
# This file is part of the pygnclib project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import sys, gzip, uuid, logging
import pyxb, csv, argparse
import re, datetime
from currency import CurrencyConverter

import gnucash, gnc, trn, cmdty, ts, split   # Bindings generated by PyXB
from fractions import Fraction

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

# assemble transaction date from CSV line
def dateFromCSV(str_value):
    return datetime.datetime.strptime(
        str_value,
        '%d/%m/%Y')

# assemble transaction date from CSV line
def strFromDate(date_value):
    return date_value.strftime('%Y-%m-%d %H:%M:%S +0100')

# convert float from CSV number string
def amountFromCSV(value):
    # assume std US locale here for the while - don't use python float
    # conversion, which is locale-dependent.
    minusIdx = value.find("-")
    preMult  = 1
    if minusIdx != -1:
        value = value[minusIdx+1:]
        preMult = -1
    # kill all thousands separators, split off fractional part
    value_parts = value.replace(",","").split('.')
    if len(value_parts) == 1:
        return float(value_parts[0])
    if len(value_parts) == 2:
        return  (float(value_parts[0]) + float(value_parts[1])/(10**len(value_parts[1])))
    else:
        raise IndexError

# convert number to integer string (possibly via conversion to rational number)
def gnucashFromAmount(value):
    rational_value = Fraction(value).limit_denominator(1000)
    return str(rational_value.numerator)+"/"+str(rational_value.denominator)

# lookup account with given name in dict (or search in xml tree)
accounts = {}
def lookupAccountUUID(accounts, xml_tree, account_name):
    if accounts.has_key(account_name):
        return accounts[account_name]
    else:
        for elem in xml_tree:
            # get account with matching name (partial match is ok)
            if elem.name.find(account_name) != -1:
                accounts[account_name] = elem.id.value()
                return elem.id.value()
    print "Did not find account with name %s in current book, bailing out!" % account_name
    exit(1)

# enter current time as "date entered"
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S +0100')

# add a simple two-sided gnucash split transaction with the given data
def createTransaction(transaction_date, account1_uuid, account1_memo, account2_uuid, account2_memo,
                      transaction_currency, transaction_value, transaction_description):
    try:
        # create a new transaction with two splits - just lovely this
        # pyxb design - the below is written by _just_ looking at the
        # rng schema
        return gnc.transaction(
            trn.id( uuid.uuid4().hex, type="guid" ),
            trn.currency( cmdty.space("ISO4217"), cmdty.id(transaction_currency) ),
            trn.date_posted( ts.date(transaction_date) ),
            trn.date_entered( ts.date(now) ),
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
            version="2.0.0" )
    except pyxb.UnrecognizedContentError as e:
        print '*** ERROR validating input:'
        print 'Unrecognized element "%s" at %s (details: %s)' % (e.content.expanded_name, e.content.location, e.details())

def default_importer(createTransaction, account1_uuid, account2_uuid,
                     transaction_ref, transaction_order_date,
                     transaction_payment_date, transaction_status, transaction_name, transaction_value, transaction_convertedvalue,
                     transaction_currency, transaction_defaultcurrency, transaction_method, transaction_brand, transaction_comment,
                     transaction_description):
    return createTransaction(transaction_payment_date, account1_uuid, "Unknown transaction - %s (%s)" % (transaction_ref, transaction_comment),
                             account2_uuid, "Unknown Concardis", transaction_defaultcurrency, transaction_convertedvalue,
                             "Concardis %s from %s by %s - %s %s" % (transaction_description, transaction_name, transaction_method,
                                                                     transaction_currency, transaction_value))

# main script
parser = argparse.ArgumentParser(description="Import Concardis transactions from CSV",
                                 epilog="Extend this script by plugin snippets, that are simple python scripts with the following "
                                 "at the toplevel namespace (example):"
                                 "desc_method_brand = 'DonationsCompleted'"
                                 "account1_name     = 'Concardis'"
                                 "account2_name     = 'Donations'"
                                 "def importer(funcCreateTrns, 17args): return funcCreateTrns(...)")
parser.add_argument("-v", "--verbosity", action="count", default=0, help="Increase verbosity by one (defaults to off)")
parser.add_argument("-p", "--pretty", action="store_true", default=False, help="Export xml pretty-printed (defaults to off)")
parser.add_argument("-d", "--delimiter", default=';', help="Delimiter used in the CSV file (defaults to ';')")
parser.add_argument("-q", "--quotechar", default='"', help="Quote character used in the CSV file (defaults to '\"')")
parser.add_argument("-e", "--encoding", default='utf-8', help="Character encoding used in the CSV file (defaults to utf-8)")
parser.add_argument("-c", "--currency", default="EUR", help="Currency all transactions are converted into (defaults to EUR)")
parser.add_argument("-s", "--script", action="append", help="Plugin snippets for sorting into different accounts")
parser.add_argument("ledger_gnucash", help="GnuCash ledger you want to import into")
parser.add_argument("concardis_csv", help="Concardis CSV export you want to import")
parser.add_argument("output_gnucash", help="Output GnuCash ledger file")
args = parser.parse_args()

gncfile = args.ledger_gnucash
csvfile = args.concardis_csv
outfile = args.output_gnucash

logger = logging.StreamHandler()
logger.setLevel(logging.INFO if args.verbosity > 0 else logging.ERROR)
logging.getLogger('').addHandler(logger)

if args.verbosity > 0: print "Opening gnc file"

# read GnuCash data
try:
    f = gzip.open(gncfile)
    gncxml = f.read()
except:
    f = open(gncfile)
    gncxml = f.read()

# read concardis csv data
concardis_csv = csv.DictReader(open(csvfile), delimiter=args.delimiter, quotechar=args.quotechar)

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
        conversion_scripts[eval(ns_name+".desc_method_brand")] = ns_name

if args.verbosity > 0: print "Importing CSV transactions"

converter = CurrencyConverter(verbosity=args.verbosity)
for index,line in enumerate(concardis_csv):
    transaction_ref = line["REF"]
    transaction_order_date = dateFromCSV(line["ORDER"])
    transaction_payment_date = dateFromCSV(line["PAYDATE"])
    transaction_status = line["STATUS"]

    # remove crap, encode into unicode
    try:
        transaction_name = re.sub(r"[\x01-\x1F\x7F]", "", line["NAME"])
    except:
        if args.verbosity > 0: print "Failing line cleanse: %s" % str(line)
    transaction_name = transaction_name.decode(args.encoding, errors='ignore')

    transaction_value = amountFromCSV(line["TOTAL"])
    transaction_currency = line["CUR"]

    transaction_method = line["METHOD"]
    transaction_brand = line["BRAND"]

    transaction_comment = line["TICKET"]
    transaction_description = line["DESC"]

    # stick unmatched transactions into Imbalance account
    account1_name = "Concardis"
    account2_name = "Imbalance"
    importer = default_importer

    # find matching conversion script
    lookup_key = transaction_description+transaction_method+transaction_brand
    if conversion_scripts.has_key(lookup_key):
        account1_name = eval(conversion_scripts[lookup_key]+".account1_name")
        account2_name = eval(conversion_scripts[lookup_key]+".account2_name")
        importer = eval(conversion_scripts[lookup_key]+".importer")

    # obtain account UUIDs
    account1_uuid = lookupAccountUUID(accounts, doc.book.account, account1_name)
    account2_uuid = lookupAccountUUID(accounts, doc.book.account, account2_name)

    # run it
    new_trn = importer(createTransaction, account1_uuid, account2_uuid,
                       transaction_ref, strFromDate(transaction_order_date), strFromDate(transaction_payment_date), transaction_status,
                       transaction_name, transaction_value,
                       converter.convert(transaction_value, transaction_currency, args.currency, transaction_payment_date.date()),
                       transaction_currency, args.currency, transaction_method, transaction_brand, transaction_comment,
                       transaction_description)

    # add it to ledger
    doc.book.append(new_trn)

if args.verbosity > 0: print "Writing resulting ledger"

# write out amended ledger
out = open(outfile, "wb")
if args.pretty:
    dom = doc.toDOM()
    out.write( dom.toprettyxml(indent=" ", encoding='utf-8') )
else:
    out.write( doc.toxml(encoding='utf-8') )
