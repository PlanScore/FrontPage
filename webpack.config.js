const path = require('path');
// the list of .js6 entry point files
// in addition to being ES2015 JavaScript code, these may require() the .src.html and .less files to also be compiled into their own outputs
// tip: require()ing other stuff, or even having JavaScript code in the file, is typical but optional
// you could have a .js6 file which effectively only serves to create a bundle of third-party code or a shared stylesheet

const GLOBAL_JS6_FILES = [
    // home page and peripheral pages
    './index.js6',
    './error.js6',
    './sitewide.js6',
    './patternlibrary/index.js6',
    './patternlibrary_htmltemplate/index.js6',
];

const STATE_JS6_FILES = [
    // per state pages, which really just use the same _statetemplate template
    './alabama/index.js6',
    './alaska/index.js6',
    './arizona/index.js6',
    './arkansas/index.js6',
    './california/index.js6',
    './colorado/index.js6',
    './connecticut/index.js6',
    './delaware/index.js6',
    './florida/index.js6',
    './georgia/index.js6',
    './hawaii/index.js6',
    './idaho/index.js6',
    './illinois/index.js6',
    './indiana/index.js6',
    './iowa/index.js6',
    './kansas/index.js6',
    './kentucky/index.js6',
    './louisiana/index.js6',
    './maine/index.js6',
    './maryland/index.js6',
    './massachusetts/index.js6',
    './michigan/index.js6',
    './minnesota/index.js6',
    './mississippi/index.js6',
    './missouri/index.js6',
    './montana/index.js6',
    './nebraska/index.js6',
    './nevada/index.js6',
    './new_hampshire/index.js6',
    './new_jersey/index.js6',
    './new_mexico/index.js6',
    './new_york/index.js6',
    './north_carolina/index.js6',
    './north_dakota/index.js6',
    './ohio/index.js6',
    './oklahoma/index.js6',
    './oregon/index.js6',
    './pennsylvania/index.js6',
    './rhode_island/index.js6',
    './south_carolina/index.js6',
    './south_dakota/index.js6',
    './tennessee/index.js6',
    './texas/index.js6',
    './utah/index.js6',
    './vermont/index.js6',
    './virginia/index.js6',
    './washington/index.js6',
    './west_virginia/index.js6',
    './wisconsin/index.js6',
    './wyoming/index.js6',
];

const JS6_FILES = [
    ...GLOBAL_JS6_FILES,
    ...STATE_JS6_FILES,
]

/////////////////////////////////////////////////////////////////////////////////////////////////////////

// const ExtractTextPlugin = require("extract-text-webpack-plugin");
const StringReplacePlugin = require("string-replace-webpack-plugin");
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const ESLintPlugin = require('eslint-webpack-plugin');


const HTML_PARTIALS = {
    footer: require("./htmlpartials/footer"),
    navbar: require("./htmlpartials/navbar"),
    headtags: require("./htmlpartials/head"),
};

module.exports = {
    mode: 'development',
    /*
     * multiple entry points, one per entry
     * the [name] for each is the basename, e.g. some/path/to/thing so we can add .js and .css suffixes
     * the values are the files with their .js6 suffixes retained
     */
    entry: JS6_FILES.reduce((o, key) => { o[key.replace(/\.js6$/, '')] = key; return o; }, {}),
    output: {
        path: path.resolve(__dirname, 'WEBSITE_OUTPUT'),
        publicPath: "/WEBSITE_OUTPUT/",
        chunkFilename: '[name].js',
    },

    module: {
        rules: [
            /*
             * Plain JS files
             * just kidding; Webpack already does those without any configuration  :)
             * but we do not want to lump them in with ES6 files: they would be third-party and then run through JSHint and we can't waste time linting third-party JS
             */

            /*
             * CSS files and also SASS-to-CSS all go into one bundled X.css
             */
            {
                test: /\.s[ac]ss$/i,
                use: [
                  MiniCssExtractPlugin.loader,
                  // Translates CSS into CommonJS
                  "css-loader?url=false",
                  // Compiles Sass to CSS
                  "sass-loader",
                ],
              },

              {
                test: /\.css$/i,
                use: [MiniCssExtractPlugin.loader, "css-loader?url=false"],
              },

            /*
             * HTML Files
             * replace [hash] entities in the .src.html to generate .html
             * typically used on .js and .css filenames to include a random hash for cache-busting
             * though could be used to cache-bust nearly anything such as images
             * tip: HTML file basenames (like any) should be fairly minimal: letters and numbers, - _ . characters
             */
            {
                test: /\.src.html$/,
                use: [
                    {
                        loader: 'file-loader',
                        options: {
                            // replace .src.html with just .html
                            regExp: '([\\w\\-\.]+)\\.src\\.html$',
                            name: '[path][1].html',
                        },
                    },
                    {
                        loader: StringReplacePlugin.replace({
                        replacements: [
                            {
                                pattern: /\[hash\]/g,
                                replacement: function (match, p1, offset, string) {
                                    const randomhash = Date.now().toString();
                                    return randomhash;
                                }
                            },

                            // a series of HTML partials to be interpolated
                            {
                                pattern: /\<!--\[include_footer\]-->/g,
                                replacement: function (match, p1, offset, string) {
                                    return HTML_PARTIALS.footer;
                                }
                            },
                            {
                                pattern: /\<!--\[include_navbar\]-->/g,
                                replacement: function (match, p1, offset, string) {
                                    return HTML_PARTIALS.navbar;
                                },
                            },
                            {
                                pattern: /\<!--\[include_head\]-->/g,
                                replacement: function (match, p1, offset, string) {
                                    return HTML_PARTIALS.headtags;
                                },
                            },
                        ]})
                    },
                ]
            },

            /*
             * Files to ignore
             * Notably from CSS, e.g. background-image SVG, PNGs, JPEGs, fonts, ...
             * we do not need them processed; our stylesheets etc. will point to them in their proper place
             * webpack scans the HTML files and will throw a fit if we don't account for every single file it finds
             */
            {
                test: /\.(svg|gif|jpg|jpeg|png)$/,
                loader: 'ignore-loader'
            },
            {
                test: /\.(woff|woff2|ttf|eot)$/,
                loader: 'ignore-loader'
            }
        ]
    },


    /*
     * enable source maps, applicable to both JS and CSS
     */
    devtool: "nosources-source-map",

    /*
     * plugins for the above
     */
    plugins: [
        // Lint our JavaScript files
        new ESLintPlugin({
            failOnError: false, // TODO: flip back to true and address failures
            extensions: ['js', 'js6'],
            exclude: [
                'node_modules',
                '_common/jslibs',
                ...STATE_JS6_FILES.slice(1) // lint just one of the states
            ],
            overrideConfig: require('./.eslintrc.js')
        }),

        // CSS output from the CSS + Sass handlers above
        new MiniCssExtractPlugin({
            filename: '[name].css'
        }),
        // for doing string replacements on files
        new StringReplacePlugin(),
    ],

    /*
     * plugins for the above
     */
    devServer: {
        contentBase: './WEBSITE_OUTPUT',
        host: '0.0.0.0',
        port: 8000,
        disableHostCheck: true
    }
};
