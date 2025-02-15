from setuptools import setup, find_packages

setup(
    name="new_bot",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        'pyTelegramBotAPI>=4.12.0',
    ],
) 