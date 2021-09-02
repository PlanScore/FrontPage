//
// SHARED UTILITY FUNCTIONS
//

import { BIAS_BALANCED_THRESHOLD, COLOR_GRADIENT, BELLCURVE_SPREAD, BELLCURVE_METRIC_TO_FILENAME_SLUG, STATIC_CONTENT_ORIGIN } from './constants';


/*
 * return a structure of information about the given EG bias score:
 * whether it's strong or weak, D or R, etc.
 */
export const lookupBias = (whichmetric, score, boundtype) => {
    if (score === undefined || score === null) return 'No Data';

    const bias_threshold = BIAS_BALANCED_THRESHOLD[whichmetric];

    const abscore = Math.abs(score);
    const isbiased = abscore > bias_threshold;

    const party = score > 0 ? 'Democratic' : 'Republican';
    const partycode = party.substr(0, 1).toLowerCase();
    const otherparty = score > 0 ? 'Republican' : 'Democratic';
    const otherpartycode = otherparty.substr(0, 1).toLowerCase();

    let description = 'No Significant Bias';
    if      (abscore >= 0.20) description = `Most Biased In Favor of ${party}`;
    else if (abscore >= 0.14) description = `More Biased In Favor of ${party}`;
    else if (abscore >= 0.07) description = `Biased In Favor of ${party}`;
    else if (abscore >= bias_threshold) description = `Slightly Biased In Favor of ${party}`;

    // normalize the score onto an absolute scale from 0 (-max) to 1 (+max); that gives us the index of the color gradient entry
    const bias_spread = BELLCURVE_SPREAD[boundtype][whichmetric];
    let p_value = 0.5 + (0.5 * (score / bias_spread));
    if (p_value < 0) p_value = 0;
    else if (p_value > 1) p_value = 1;
    const color = COLOR_GRADIENT[ Math.round((COLOR_GRADIENT.length - 1) * p_value) ];

    return {
        party: party,
        partycode: partycode,
        otherparty: otherparty,
        otherpartycode: otherpartycode,
        cssclass: isbiased ? party.toLowerCase() : 'balanced',
        color: color,
        description: description,
        isbiased: isbiased,
    };
};

// the bell charts are a bit of a trick. An IMG that's stretched, then DIVs for the marker line and labels
// see also bellcurves.scss
export const drawBiasBellChart = (metricid, datavalue, htmldivid, boundtype, planorelection) => {
    const $div = $(`#${htmldivid}`);
    // Set the img src according to the combo of metricid + plan/election + office.
    $div.find('img.curveimg').remove();
    const curveimg = document.createElement('img');
    curveimg.className = 'curveimg';
    console.assert(BELLCURVE_METRIC_TO_FILENAME_SLUG[metricid]);
    curveimg.src = `${STATIC_CONTENT_ORIGIN}/images/${boundtype}_${BELLCURVE_METRIC_TO_FILENAME_SLUG[metricid]}_${planorelection}_curve.svg`;
    $div.find('div.curve').prepend(curveimg);

    // normalize the value into a range of 0% to 100% within that range, to form an X axis position
    // 0% is the furthest left; 100% furthest right; 50% balanced
    // watch out! we swap the sign here!
    // Republican bias is indicated with values <0 BUT in American parlance Republicans are "right" which is the positive-numbers side
    // so SUBTRACT the bias to shift a positive/democrat bias toward blue left
    const $markline  = $div.find('div.markline');
    const $marklabel = $div.find('div.marklabel');
    const spread = BELLCURVE_SPREAD[boundtype][metricid];
    let percentile = 0.5 - (0.5 * datavalue / spread);
    percentile = Math.min(Math.max(percentile, 0), 1);
    // console.log([ `drawBiasBellChart() ${metricid}`, spread, datavalue, percentile ]);

    $markline.css({ 'left':`${100 * percentile}%` });
    $marklabel.css({ 'left':`${100 * percentile}%` });
    $marklabel.removeClass('left').removeClass('right');
    if (percentile >= 0.90) $marklabel.addClass('right');
    if (percentile <= 0.10) $marklabel.addClass('left');

    // fill in the spread values into the +D% ad +R% legends
    const $legend = $div.find('div.metric-bellchart-legend');
    if(metricid == 'd2') {
        var spreadtext = Math.round(100 * spread) / 100;
    } else {
        var spreadtext = Math.round(100 * spread);
    }
    $legend.find('span[data-field="metric-bellchart-spread"]').text(spreadtext);
};

export const loadAnnouncementIfNeverClosed = () => {
  if (!document.cookie.split('; ').find(row => row.startsWith('closeAnnouncement'))) {
    const announcementBanner = document.createElement('div');
    announcementBanner.classList.add('announcement');
    announcementBanner.id = 'announcement';
    // edit the text lines, and the href property here to modify the banner
    announcementBanner.innerHTML = `
      Hark! Read all about it!
      <a class="cta" href="/library">
        Visit the plan library
      </a>
        <a class="close-link" onClick="closeAnnouncement()" title="Close announcement">
          <svg width="19" height="19" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M7.00007 5.60007L1.4 0L0 1.4L5.60007 7.00007L2.86885e-05 12.6001L1.40003 14.0001L7.00007 8.40007L12.6 14L14 12.6L8.40007 7.00007L14 1.4001L12.6 0.000103903L7.00007 5.60007Z" fill="white"/>
          </svg>
        </a>
      `
    document.body.insertBefore(announcementBanner, document.body.firstChild);
    document.body.classList.add('announcement-visible');
    window.scrollBy(0, -60);
  }
};

export const closeAnnouncement = () => {
  const announcementBanner = document.getElementById('announcement');
  announcementBanner.remove();
  document.cookie = "closeAnnouncement=true; max-age=604800";
  document.body.classList.remove('announcement-visible');
};
