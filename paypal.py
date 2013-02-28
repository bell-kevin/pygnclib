#!/usr/bin/env python
#
# This file is part of the pygnclib project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

import sys, gzip, uuid
import pyxb, csv

import gnucash, gnc, trn, cmdty, ts, split   # Bindings generated by PyXB
from datetime import date, datetime
from fractions import Fraction

# assemble transaction date from PayPal CSV line
def dateFromPayPalLine(line):
    payment_date = datetime.strptime(
        line["Date"] + " " + line[" Time"],
        '%d.%m.%Y %H:%M:%S')
# %z seems fixed only in 3.2
#            line["Date"] + " " + line[" Time"] + " " + line[" Time Zone"],
#            '%d.%m.%Y %H:%M:%S GMT%z').utcoffsetset()
    return payment_date.strftime('%Y-%m-%d %H:%M:%S +0100')

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

# main script
if len(sys.argv) > 2:
    gncfile = sys.argv[1]
    csvfile = sys.argv[2]
else:
    print "Usage: paypal.py <gnucash_file> <paypal_csv>"
    exit(1)

# read GnuCash data
try:
    f = gzip.open(gncfile)
    gncxml = f.read()
except:
    f = open(gncfile)
    gncxml = f.read()

# read paypal csv data
paypal_csv = csv.DictReader(open(csvfile), delimiter='\t', quotechar='"')

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

# enter current time as "date entered"
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S +0100')
old_lines = []
for index,line in enumerate(paypal_csv):
    if line[" Type"] == "Currency Conversion":
        old_lines.append( line )
    else:
        #Withdraw Funds to a Bank Account, Donations, Update to eCheck Received,
        transaction_date = dateFromPayPalLine(line)
        transaction_title = u"PayPal:Donations from %s" % line[" Name"].decode('iso-8859-1')
        transaction_amount = amountFromPayPal(line[" Net"])

        # create a new transaction with two splits - just lovely this
        # pyxb design - the below is written by _just_ looking at the
        # rng schema
        new_trn = gnc.transaction(
            trn.id( uuid.uuid4().hex, type="guid" ),
            trn.currency( cmdty.space("ISO4217"), cmdty.id("EUR") ),
            trn.date_posted( ts.date(transaction_date) ),
            trn.date_entered( ts.date(now) ),
            trn.description(transaction_title),
            trn.splits(
                trn.split(
                    split.id( uuid.uuid4().hex, type="guid" ),
                    split.memo( "Account Foo, bank bar" ),
                    split.reconciled_state( "c" ),
                    split.value( gnucashFromAmount(transaction_amount) ),
                    split.quantity( gnucashFromAmount(transaction_amount) ),
                    split.account( "101eef64413910c2df39caf80e806891", type="guid" )),
                trn.split(
                    split.id( uuid.uuid4().hex, type="guid" ),
                    split.memo( "Account Bar, from foo" ),
                    split.reconciled_state( "n" ),
                    split.value( gnucashFromAmount(-transaction_amount) ),
                    split.quantity( gnucashFromAmount(-transaction_amount) ),
                    split.account( "e2ad7cd1b5c6135dcfd19151c7689336", type="guid" ))),
            version="2.0.0" )

        doc.book.append(new_trn)

# done, dump to xml again
#print doc.toxml(encoding='utf-8')

dom = doc.toDOM()
print dom.toprettyxml(indent=" ", encoding='utf-8')
