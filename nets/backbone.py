from functools import wraps

from keras import backend as K
from keras.initializers import random_normal
from keras.layers import (BatchNormalization, Concatenate, Conv2D, Layer, LeakyReLU,
                          MaxPooling2D, ZeroPadding2D)
from utils.utils import compose


class SiLU(Layer):
    def __init__(self, **kwargs):
        super(SiLU, self).__init__(**kwargs)
        self.supports_masking = True

    def call(self, inputs):
        return inputs * K.sigmoid(inputs)

    def get_config(self):
        config = super(SiLU, self).get_config()
        return config

    def compute_output_shape(self, input_shape):
        return input_shape

#------------------------------------------------------#
#   单次卷积DarknetConv2D
#   如果步长为2则自己设定padding方式。
#------------------------------------------------------#
@wraps(Conv2D)
def DarknetConv2D(*args, **kwargs):
    darknet_conv_kwargs = {'kernel_initializer' : random_normal(stddev=0.02)}
    darknet_conv_kwargs['padding'] = 'valid' if kwargs.get('strides')==(2, 2) else 'same'
    darknet_conv_kwargs.update(kwargs)
    return Conv2D(*args, **darknet_conv_kwargs)
    
#---------------------------------------------------#
#   卷积块 -> 卷积 + 标准化 + 激活函数
#   DarknetConv2D + BatchNormalization + SiLU
#---------------------------------------------------#
def DarknetConv2D_BN_Leaky(*args, **kwargs):
    no_bias_kwargs = {'use_bias': False}
    no_bias_kwargs.update(kwargs)
    if "name" in kwargs.keys():
        no_bias_kwargs['name'] = kwargs['name'] + '.conv'
    return compose(
        DarknetConv2D(*args, **no_bias_kwargs),
        BatchNormalization(momentum = 0.97, epsilon = 0.001, name = kwargs['name'] + '.bn'),
        LeakyReLU(0.1))

def Transition_Block(x):
    #----------------------------------------------------------------#
    #   利用ZeroPadding2D和一个步长为2x2的卷积块进行高和宽的压缩
    #----------------------------------------------------------------#
    y = MaxPooling2D((2, 2), strides=(2, 2))(x)
    return y

def Multi_Concat_Block(x, c2, c3, n=4, e=1, ids=[0], name = ""):
    c_ = int(c2 * e)
        
    x_1 = DarknetConv2D_BN_Leaky(c_, (1, 1), name = name + '.cv1')(x)
    x_2 = DarknetConv2D_BN_Leaky(c_, (1, 1), name = name + '.cv2')(x)
    
    x_all = [x_1, x_2]
    for i in range(n):
        x_2 = DarknetConv2D_BN_Leaky(c2, (3, 3), name = name + '.cv3.' + str(i))(x_2)
        x_all.append(x_2)
    y = Concatenate(axis=-1)([x_all[id] for id in ids])
    y = DarknetConv2D_BN_Leaky(c3, (1, 1), name = name + '.cv4')(y)
    return y

#---------------------------------------------------#
#   CSPdarknet的主体部分
#   输入为一张640x640x3的图片
#   输出为三个有效特征层
#---------------------------------------------------#
def darknet_body(x, transition_channels, block_channels, n):
    #-----------------------------------------------#
    #   输入图片是640, 640, 3
    #-----------------------------------------------#
    ids = [-1, -2, -3, -4]
    #---------------------------------------------------#
    #   base_channels 默认值为64
    #---------------------------------------------------#
    # 320, 320, 3 => 320, 320, 64
    x = ZeroPadding2D(((1, 1),(1, 1)))(x)
    x = DarknetConv2D_BN_Leaky(transition_channels * 2, (3, 3), strides = (2, 2), name = 'backbone.stem')(x)
    
    # 320, 320, 64 => 160, 160, 128
    x = ZeroPadding2D(((1, 1),(1, 1)))(x)
    x = DarknetConv2D_BN_Leaky(transition_channels * 4, (3, 3), strides = (2, 2), name = 'backbone.dark2.0')(x)
    x = Multi_Concat_Block(x, block_channels * 2, transition_channels * 4, n=n, ids=ids, name = 'backbone.dark2.1')
    
    # 160, 160, 128 => 80, 80, 256
    x = Transition_Block(x)
    x = Multi_Concat_Block(x, block_channels * 4, transition_channels * 8, n=n, ids=ids, name = 'backbone.dark3.1')
    feat1 = x
    
    # 80, 80, 256 => 40, 40, 512
    x = Transition_Block(x)
    x = Multi_Concat_Block(x, block_channels * 8, transition_channels * 16, n=n, ids=ids, name = 'backbone.dark4.1')
    feat2 = x
    
    # 40, 40, 512 => 20, 20, 1024
    x = Transition_Block(x)
    x = Multi_Concat_Block(x, block_channels * 16, transition_channels * 32, n=n, ids=ids, name = 'backbone.dark5.1')
    feat3 = x
    return feat1, feat2, feat3

