import torch
import torch.nn as nn
import torchvision.models as models

import torch.nn.functional as F
import numpy as np
import math

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class EncoderCNN(nn.Module):
    def __init__(self, embed_size):
        super(EncoderCNN, self).__init__()
        resnet = models.resnet50(pretrained=True)
        for param in resnet.parameters():
            param.requires_grad_(False)
        
        modules = list(resnet.children())[:-1]
        self.resnet = nn.Sequential(*modules)
        self.embed = nn.Linear(resnet.fc.in_features, embed_size)

    def forward(self, images):
        features = self.resnet(images)
        features = features.view(features.size(0), -1)
        features = self.embed(features)
        return features
    

class DecoderRNN(nn.Module):
    def __init__(self, embed_size, hidden_size, vocab_size):
        super(DecoderRNN, self).__init__()
        
        # Keep track of hidden_size for initialization of hidden state
        self.hidden_size = hidden_size
        
        # Embedding layer that turns words into a vector of a specified size               
        self.word_embeddings = nn.Embedding(vocab_size, embed_size)
        
        # The LSTM cell takes a word vector of size embed_size and outputs a hidden representation of size hidden_size
        self.lstm = nn.LSTM(input_size = embed_size , \
                            hidden_size = hidden_size,
                            num_layers = 1,
                            bias = True,
                            batch_first = True,
                            dropout = 0,
                            bidirectional = False
                           )
        
        # Maps the hidden state to the number of words in out vocubalary
        self.linear = nn.Linear(hidden_size, vocab_size)
        
    def init_hidden(self, batch_size):
        """ At the start of training, we need to initialize a hidden state;
        there will be none because the hidden state is formed based on previously seen data.
        So, this function defines a hidden state with all zeroes
        The axes semantics are (num_layers, batch_size, hidden_dim)
        """
        
        return (torch.zeros((1, batch_size, self.hidden_size), device = device) , torch.zeros((1, batch_size, self.hidden_size), device = device))
                
        
    def forward(self, features, captions):
        
        # Discard the <end> word to avoid predicting when <end> is the input of the RNN
        captions = captions[:, :-1]
        
        # Initialize the hidden state
        batch_size = features.shape[0] # shape of the features is (batch_size, embed_size)
        
        self.hidden = self.init_hidden(batch_size)
        
        # Create embedded word vectors for each word in the captions
        embeddings = self.word_embeddings(captions) # embeddings shape = (batch_size, caption_length - 1, embed_size)
        
        embeddings = torch.cat((features.unsqueeze(1), embeddings), dim=1) # embeddings new shape= (batch_size, caption length, embed_size)
        
        # Get the output and hidden state by passing the lstm over our word embeddings
        # the lstm takes in our embeddings and hidden state
        lstm_out, self.hidden = self.lstm(embeddings, self.hidden)
        
        # Fully connected layer
        outputs = self.linear(lstm_out) # output shape = (batch_size, caption_length, vocab_size)
        
        return outputs

    def sample(self, inputs, states=None, max_len=20):
        " accepts pre-processed image tensor (inputs) and returns predicted sentence (list of tensor ids of length max_len) "
        
        output = []
        batch_size = inputs.shape[0] # batch_size is 1 at inference, inputs shape : (1, 1, embed_size)
        hidden = self.init_hidden(batch_size) # Get initial hidden state of the LSTM
        
        while True:
            lstm_out, hidden = self.lstm(inputs, hidden) # lstm_out shape = (1, 1, hidden_size)
            outputs = self.linear(lstm_out) # outputs shape = (1, 1, vocab_size)
            outputs = outputs.squeeze(1) # outputs shape = (1, vocab_size)
            _, max_indice = torch.max(outputs, dim=1) # predict the most likely next word, max_indice shape = (1)
            
            output.append(max_indice.cpu().numpy()[0].item()) # storing the word predicted

            if(max_indice == 1):
                # We predicted the <end> word, so there is no further prediction to do
                break

            ## Prepare to embed the last predicted word to be the new input of the lstm
            inputs = self.word_embeddings(max_indice) # inputs shape = (1, embed_size)
            inputs = inputs.unsqueeze(1) # inputs shape = (1, 1, embed_size)
            
        return output
    
    def get_outputs(self, inputs, hidden):
        lstm_out, hidden = self.lstm(inputs, hidden) # lstm_out shape = (1, 1, hidden_size)
        outputs = self.linear(lstm_out) # outputs shape = (1, 1, vocab_size)
        outputs = outputs.squeeze(1) # outputs shape = (1, vocab_size)
        
        return outputs, hidden
    
    def get_next_word_input(self, max_indice):
        
        ## Prepare to embed the last predicted word to be the new input of the lstm
        inputs = self.word_embeddings(max_indice) # input shape = (1, embed_size)
        inputs = inputs.unsqueeze(1) # input shape = (1, 1, embed_size)
        
        return inputs
    
    def beam_search_sample(self, inputs, beam=3):
        outputs = []
        batch_size = inputs.shape[0] # batch_size is 1 a inference , input shape = (1, 1, embed_size)
        hidden = self.init_hidden(batch_size) # initial hidden state of the LSTM
        
        # sequences[0][0] : index of start word
        # sequences[0][1] : probability of the word predicted
        # sequences[0][2] : hidden state related of the last word
        sequences = [[[torch.Tensor([0])], 1.0, hidden]]
        max_len = 20
        
        ## Step 1
        # Predict the first word <start>
        outputs, hidden = DecoderRNN.get_outputs(self, inputs, hidden)
        _, max_indice = torch.max(outputs, dim=1) # predict the most likely next word, max_indice shape : (1)
        outputs.append(max_indice.cpu().numpy()[0].item()) # storing the word predicted
        
        l = 0
        while len(sequences[0][0]) < max_len :
            print("length: ", l)
            l += 1
            temp = []
            for seq in sequences:
                inputs = seq[0][-1] # last word index in seq
                inputs = inputs.type(torch.cuda.LongTensor)
                print("inputs: ", inputs)
                # Embed the input word
                inputs = self.word_embeddings(word_inputs) # inputs shape = (1, embed_size)
                inputs = inputs.unsqueeze(1) # input shape = (1, 1, embed_size)
                
                # retrieve the hidden state
                hidden = seq[2]
                
                probs, hidden = DecoderRNN.get_outputs(self, inputs, hidden)
                
                # Getting the top <beam_index>(n) predictions
                softmax_score = F.log_softmax(outputs, dim=1) # Define a function to sort the cumulative score
                sorted_score, indices = torch.sort(-softmax_score, dim=1)
                words_preds = indices[0][:beam]
                best_scores = sorted_score[0][:beam]
                
                # Creating a new list so as to put them via the model again
                for i, w in enumerate(words_preds):
                    
                    next_cap, prob = seq[0][0].cpu().numpy().tolist(), seq[1]
                    
                    next_cap.append(w)
                    print("next_cap :", next_cap)
                    prob*best_scores[i].cpu().item()
                    temp.append([next_cap, prob])
                    
            sequences = temp
            # Order according to proba
            ordered = sorted(sequences, key = lambda tup: tup[1])
            # Getting the top words
            sequences = ordered[:beam]
            print("sequences: ", sequences)
            