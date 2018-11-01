from setuptools import setup, find_packages

version = "0.2"

requires = [
    "aiohttp",
    "aiodns",
    "cchardet",
]

entry_points = {
    'console_scripts': [
        'cdb_init=dozorro.api.main:cdb_init',
        'sync_tenders=dozorro.api.sync_tenders:main'
    ]
}

setup(
    name="dozorro.api",
    version=version,
    description="Dozorro Database API",
    # long_description will be there
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python",
    ],
    keywords="web services",
    author="Volodymyr Flonts",
    author_email="vflonts@gmail.com",
    license="Apache License 2.0",
    url="https://github.com/dozorro",
    packages=find_packages(),
    namespace_packages=["dozorro"],
    include_package_data=True,
    zip_safe=False,
    install_requires=requires,
    entry_points=entry_points
)
