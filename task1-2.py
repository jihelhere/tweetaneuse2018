#!/bin/env python

from __future__ import print_function
import time

from collections import defaultdict
import random
import math
import sys
import argparse

import dynet as dy
import pdb

import deft_data
from networks import Hybrid_BiLSTM, mlp

parser = argparse.ArgumentParser()
parser.add_argument("--task2", dest="task2", action="store_true")
parser.add_argument("--iter", type=int, default=10, help="Number of iterations.")

parser.add_argument("--char-emb-size", type=int, default=32, help="size of char embeddings.")
parser.add_argument("--word-emb-size", type=int, default=64, help="size of word embeddings.")
parser.add_argument("--word-hidden-size", type=int, default=128, help="size of bilstm hidden layers.")
parser.add_argument("--batch-size", type=int, default=16, help="size of batches.")
parser.add_argument("--dropout-rate", type=float, default=0.5, help="dropout rate during training")

args = parser.parse_args()

# format of files: each line is "ID"\t"string"
# "791363815107465216"	"20h51 : +20min (malaise voyageur avec prise en charge de la personne à Trilport) #ligneP"
train_file = "data/id_tweets"
train_categories = "data/cat_tweets"


# DyNet Starts
model = dy.Model()
trainer = dy.AmsgradTrainer(model)

class deft_t12_nn:
    def __init__(self, model, data):
        self.hbilstm = Hybrid_BiLSTM(model, data, args.char_emb_size, args.word_emb_size, args.word_hidden_size, 1, 1, args.dropout_rate)
        self.classif = mlp(model, [args.word_hidden_size,args.word_emb_size, data.output_size], dy.rectify, args.dropout_rate)
        self.data = data

    def calc_output(self, sents, train_mode):
        dy.renew_cg()

        fw,bw = self.hbilstm.calc_output(sents, train_mode)
        finale  = fw[-1] + bw[-1]

        if train_mode:
            finale = dy.dropout(finale, args.dropout_rate)

        self.classif.prepare_batch()

        out = self.classif(finale, train_mode)
        return out

    def calc_loss(self, sents):
        o = self.calc_output(sents, True)
        ys = [self.data.map_cat(y) for (x,y) in sents]
        e = dy.pickneglogsoftmax_batch(o, ys)
        return e

    def predict(self, sents):
        e = self.calc_output(sents, False)

        if args.task2:
            res = [0,0,0,0]
            total = [0,0,0,0]
        else:
            res = [0,0]
            total = [0,0]

        ys = [self.data.map_cat(y) for (x,y) in sents]

        #print (e.dim())
        n = 0
        #print (ys)
        for i in range(len(ys)):
            b = dy.pick_batch_elem(e,i)
            v = dy.argmax(b, gradient_mode="zero_gradient")
            v = v.vec_value()
            #print(v)
            #print(ys[i],v.index(max(v)))
            if ys[i] == v.index(max(v)):
                res[ys[i]] += 1
            total[ys[i]] += 1
            #print (e.dim())
            #print(n)
        return res,total



# Creates batches where all source sentences are the same length
def create_batches(sorted_dataset, max_batch_size):
    source = [x[0] for x in sorted_dataset]
    src_lengths = [len(x.split()) for x in source]
    batches = []
    prev = src_lengths[0]
    prev_start = 0
    batch_size = 1
    for i in range(1, len(src_lengths)):
        if src_lengths[i] != prev or batch_size == max_batch_size:
            batches.append((prev_start, batch_size))
            prev = src_lengths[i]
            prev_start = i
            batch_size = 1
        else:
            batch_size += 1
    return batches



def train_iter(mynet, K, train, train_order, dev, dev_order):
    num_sentence = 0
    train_loss = 0.0
    start_time = time.time()


    random.shuffle(train_order)
    for sent_id, (start, length) in enumerate(train_order):
        #print (sent_id,length)
        train_batch = train[start:start+length]
        e = mynet.calc_loss(train_batch)
        e = dy.sum_batches(e)
        train_loss += e.value()
        num_sentence += length
        e.backward()
        trainer.update()
        if (sent_id+1) % 100 == 0:
            print("--finished %r sentences" % (sent_id+1))
    end_time = time.time()
    print("iter %r: train loss/sent=%.4f, time=%.2fs" % (K, train_loss/num_sentence, end_time-start_time))

    start_time = time.time()
    n = 0
    num_sentence = 0

    if args.task2:
        res   = [0,0,0,0]
        total = [0,0,0,0]
    else:
        res   = [0,0]
        total = [0,0]

    for sent_id, (start, length) in enumerate(dev_order):
        #print (sent_id,length)
        dev_batch = dev[start:start+length]
        o,t = mynet.predict(dev_batch)
        n += sum(o)
        for i in range(len(res)):
            res[i] += o[i]
            total[i] += t[i]
        num_sentence += length
        if (sent_id+1) % 100 == 0:
            print("--finished %r sentences" % (sent_id+1))
    end_time = time.time()
    print("iter %r: dev acc =%.4f, time=%.2fs" % (K, float(n)/float(num_sentence), end_time-start_time))
    for i in range(len(res)):
        print("cat: %r : dev acc =%.4f, (%r/%r)" % (i, float(res[i])/float(total[i]), res[i], total[i]))






def main():
    if args.task2:
        all_data = deft_data.task2(train_file, train_categories, 10)
    else:
        all_data = deft_data.task1(train_file, train_categories, 10)

    train = list(all_data.id_to_text_cat_map.values())

    random.shuffle(train)
    l = len(train)
    dev = train[int(0.9 *l):]
    train = train[:int(0.9*l)]


    train.sort(key=lambda t: len(t[0].split()), reverse=True)
    dev.sort(key=lambda t: len(t[0].split()), reverse=True)

    print (len(train))
    train_order = create_batches(train, args.batch_size)
    print (len(train_order))

    print (len(dev))
    dev_order = create_batches(dev, args.batch_size)
    print (len(dev_order))

    net = deft_t12_nn(model, all_data)

    for ITER in range(args.iter):
        train_iter(net, ITER, train, train_order, dev, dev_order)

if __name__ == '__main__':
    main()
