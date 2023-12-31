import sudrfparser
import json
import urllib
import re
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

###
# Functions to parse criminal cases of the first instance from the official portal 'Pravosudie' (https://bsr.sudrf.ru/bigs/portal.html);
# Searching in court cases by keywords;
# Uses Chrome driver
# Developed by Dataout.org
# CC-BY-SA 4.0
###

def _get_case_text_and_metadata(browser) -> dict:
    '''
    Getting text and metadata of a single case from the case page
    A subfunction for "get_cases_by_keywords"
    '''

    case_info = {}
    case_info["metadata"] = {}

    # collect case metadata (the tab "Дело")
    browser.find_element(By.XPATH, '//*[@id="cardContainer"]/div[2]/div/div/ul/li[1]/label').click()

    # collect metadata
    ### accused info
    accused_list = []
    soup = BeautifulSoup(browser.page_source, 'html.parser')
    accused_content = soup.find("div",{"class":"sudrf-dt"}).find_all('tr')

    for tr in accused_content[1:]:
        accussed_dict = {}
        accussed_dict["name"] = tr.find_all('td')[0].text
        
        # ensuring that the table column contains articles and not other info by checking "УК РФ" in text
        for td in tr.find_all("td"):
            if "УК РФ" in td.text:
                accussed_dict["article"] = td.text.rstrip("УК РФ").split(';')
            
        accused_list.append(accussed_dict)

    case_info["metadata"]["accused"] = accused_list
    
    ### judge
    try:
        judge = browser.find_element(By.XPATH,'//*[@id="bookmark0"]/ul[1]/li[2]/div/table/tbody/tr[1]/td[2]/div/div/a').text
    except:
        judge = ""

    case_info["metadata"]["judge"] = judge

    # switching to the case text "Судебные акты": click on the tab first, then switch to frame
    browser.find_element(By.XPATH, '//*[@id="cardContainer"]/div[2]/div/div/ul/li[3]/label').click()
    browser.switch_to.frame(browser.find_element(By.TAG_NAME, "iframe"))
    soup = BeautifulSoup(browser.page_source, 'html.parser')
    # save text
    case_text = soup.find("body").text.replace('"','\'').replace('\xa0','')
    case_info["case_text"] = case_text

    return case_info

def _parse_bsr_case_info(result_list:list) -> list:
    '''
    Parsing cases info from the results page; used for get_cases_links
    Takes a list of found cases
    result_list: list
    Returns a list of dicts with metadata of each case
    '''
    cases = []

    for li in result_list:

        case_info = {}
        case_info["metadata"] = {}

        case_url = li.find("a",{"class":"resultHeader"})["href"]
        case_id = re.search("(id=.*&shard=)",case_url)[0].replace("id=","").replace("&shard=","")
        case_name = li.find("div",{"class":"bgs-result"}).a.contents[0]
        id_text = case_name.replace("Уголовное дело ","")

        # additional metadata
        court_name = ""
        adm_date = ""
        decision_result = ""

        for field in li.find("span", {"class": "resultHeaderAttributes"}).find_all("span",class_="additional-field-value"):
            if "Наименование суда" in field["data-comment"]:
                court_name = field.span.contents[0]
            if "Дата поступления" in field["data-comment"]:
                adm_date = field.span.contents[0]
            if "Результат" in field["data-comment"]:
                decision_result = field.span.contents[0]

        case_info["case_url"] = case_url
        case_info["case_id_uid"] = case_id
        case_info["metadata"]["id_text"] = id_text
        case_info["metadata"]["court_name"] = court_name
        case_info["metadata"]["adm_date"] = adm_date
        case_info["metadata"]["decision_result"] = decision_result

        cases.append(case_info)

    return cases

def get_cases_links(path_to_driver:str, keywords:list, start_date:str, end_date:str, path_to_save="") -> dict:
    '''
    path_to_driver: str, path to Chrome driver;
    keywords: list, keywords (words and phrases) to search for in cases texts, for example, ["ключевое слово", "ещё одно слово"];
    start_date: str, format 'YYYY-MM-DD', for example, '2023-01-30';
    end_date: str, format 'YYYY-MM-DD', for example, '2023-12-31';
    path_to_save: str, directory where to save files and logs, default is "";
    Saves a json file (dict) with keywords as keys and a list of links to cases as values
    Returns a dict: {"keyword":["link_to_case"]}
    Used in get_cases_by_keywords
    '''

    results = {}

    browser = sudrfparser._set_browser(path_to_driver)

    # generating a request ID based on local time
    timestamp = time.localtime()
    request_id = f"{timestamp[3]}-{timestamp[4]}-{timestamp[5]}-{timestamp[2]}-{timestamp[1]}-{timestamp[0]}"

    for keyword in keywords:

        results_per_keyword = {}
        all_cases_per_keyword = []

        # shaping a request link per keyword
        request_link = '''https://bsr.sudrf.ru/bigs/portal.html#{"type":"MULTIQUERY","multiqueryRequest":{"queryRequests":[{"type":"Q","queryRequestRole":"SIMPLE","request":"{\\"query\\":\\"''' + keyword + '''\\",\\"type\\":\\"NEAR\\",\\"mode\\":\\"SIMPLE\\"}","operator":"AND"},{"type":"Q","request":"{\\"mode\\":\\"EXTENDED\\",\\"typeRequests\\":[{\\"fieldRequests\\":[{\\"name\\":\\"case_user_doc_entry_date\\",\\"operator\\":\\"B\\",\\"query\\":\\"''' + start_date + '''T00:00:00\\",\\"sQuery\\":\\"''' + end_date + '''T00:00:00\\",\\"fieldName\\":\\"case_user_doc_entry_date\\"}],\\"mode\\":\\"AND\\",\\"name\\":\\"common\\",\\"typesMode\\":\\"AND\\"}]}","operator":"AND","queryRequestRole":"CATEGORIES"}]},"sorts":[{"field":"score","order":"desc"}],"simpleSearchFieldsBundle":"ug","noOrpho":false,"rows":20}'''

        # encoding the request link
        request_link_encoded = urllib.parse.quote(request_link,safe='/:#,=&')

        browser.get(request_link_encoded)
        # checking if the content is loaded and visible
        check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","resultsList", 30)

        if check_content == True:

            soup = BeautifulSoup(browser.page_source, 'html.parser')

            # check if results are found
            result_list = soup.find("ul",{"id":"resultsList"}).find_all("li")

            if result_list[0].text == "Ничего не найдено":
                results_per_keyword = {"n_cases":0}

            else:
                results_per_keyword = {}
                n_cases = int(soup.find("div",{"id":"resultCount"})["data-total"])
                results_per_keyword["n_cases"] = n_cases

                # adding results from the first page
                all_cases_per_keyword.extend(_parse_bsr_case_info(result_list))
                
                # n_pages
                n_pages = n_cases // 20 # max 20 cases per page
                if n_cases % 20 != 0: # if there's a leftover, add a page
                    n_pages += 1

                # iterate over all pages
                if n_pages > 1:
                
                    # get a session uid from the first case url
                    session_uid = re.search("(\\d|\\w){8}-((\\d|\\w){4}-){3}(\\d|\\w){12}",all_cases_per_keyword[0]["case_url"])[0]

                    for i in range(20,n_cases,20):

                        # opening pages in a new tab to avoid captcha
                        # the first page stays open on the first tab
                        browser.execute_script("window.open('');")
                        browser.switch_to.window(browser.window_handles[1])

                        pagination = '''https://bsr.sudrf.ru/bigs/portal.html#{"start":'''+ str(i) + ''',"rows":20,"uid":"''' + session_uid + '''","type":"MULTIQUERY","multiqueryRequest":{"queryRequests":[{"type":"Q","queryRequestRole":"SIMPLE","request":"{\\"query\\":\\"''' + keyword + '''\\",\\"type\\":\\"NEAR\\",\\"mode\\":\\"SIMPLE\\"}","operator":"AND"},{"type":"Q","request":"{\\"mode\\":\\"EXTENDED\\",\\"typeRequests\\":[{\\"fieldRequests\\":[{\\"name\\":\\"case_user_doc_entry_date\\",\\"operator\\":\\"B\\",\\"query\\":\\"''' + start_date + '''T00:00:00\\",\\"sQuery\\":\\"''' + end_date + '''T00:00:00\\",\\"fieldName\\":\\"case_user_doc_entry_date\\"}],\\"mode\\":\\"AND\\",\\"name\\":\\"common\\",\\"typesMode\\":\\"AND\\"}]}","operator":"AND","queryRequestRole":"CATEGORIES"}]},"sorts":[{"field":"score","order":"desc"}],"simpleSearchFieldsBundle":"ug","noOrpho":false,"facet":{"field":["type"]},"facetLimit":21,"additionalFields":["court_document_documentype1","court_case_entry_date","court_case_result_date","court_subject_rf","court_name_court","court_document_law_article","court_case_result","case_user_document_type","case_user_doc_entry_date","case_user_doc_result_date","case_doc_subject_rf","case_user_doc_court","case_doc_instance","case_document_category_article","case_user_doc_result","case_user_entry_date","m_case_user_type","m_case_user_sub_type","ora_main_law_article"],"hlFragSize":1000,"groupLimit":3,"woBoost":false}'''

                        # encoding the request link
                        pagination_encoded = urllib.parse.quote(pagination,safe='/:#,=&')

                        browser.get(pagination_encoded)
                        # checking if the content is loaded and visible
                        check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","resultsList",30)
                        # additional wait to avoid captcha
                        time.sleep(3)

                        soup = BeautifulSoup(browser.page_source, 'html.parser')

                        # adding cases info to all_cases_per_keyword
                        result_list = soup.find("ul",{"id":"resultsList"}).find_all("li")
                        all_cases_per_keyword.extend(_parse_bsr_case_info(result_list))

                        # closing the tab and switching to the first tab
                        browser.close()
                        browser.switch_to.window(browser.window_handles[0])

                        # additional wait for every 10th page (200 cases) to avoid captcha
                        if i % 200 == 0:
                            time.sleep(5)

        else:
            results_per_keyword = "request_failed"

        browser.close()

        results_per_keyword["cases"] = all_cases_per_keyword
        results[keyword] = results_per_keyword

        # save a json file
        results_file_name = f"{path_to_save}/cases_links_{request_id}.json"
        with open(results_file_name, 'w') as jf:
            json.dump(results, jf, ensure_ascii=False)

    return results

def _get_court_website_srv(court_name:str) -> tuple:
    
    court_codes_url = "https://github.com/dataout-org/sudrfparser/raw/main/courts_info/sudrf_websites.json"
    r = requests.get(court_codes_url)
    court_codes = r.json()
    
    info_to_return = ()
    
    for region_code, courts_info in court_codes.items():
        for court in courts_info:
            if court_name in court["court_name"]:
                info_to_return = (court["court_website"], court["srv"])
                
    return info_to_return


def _get_captcha_from_soup_f1(soup_captcha) -> str:
    '''
    '''
    # finding the first table in the form
    content = soup_captcha.find("div", {"id": "content"}).find("table")
    # getting captcha ID
    captcha_id = content.find("input", {"name": "captchaid"})["value"]

    imgstring = content.find("img")["src"].split(",")[1]
    imgdata = base64.b64decode(imgstring)
    # enlarging the captcha image
    display(Image(imgdata, width=400, height=200))

    # entering captcha manually
    captcha_entered = input("Enter captcha: ")
    captcha_addition = f"&captcha={captcha_entered}&captchaid={captcha_id}"

    return captcha_addition


def _get_case_link_f1(soup) -> list:
    '''
    '''
    table_rows = soup.find("table", {"id": "tablcont"}).find_all("tr")
    case_link = []
    
    for row in table_rows:
        # taking only the first column
        first_cell = row.find("td")
        if first_cell != None:
            case_link.append(first_cell.find("a")['href'])
            
    return case_link

def _get_case_by_id_f1(browser,id_text:str,court_website:str,adm_date:str,srv_num:list,captcha:str,soup_captcha='') -> dict:
    '''
    '''

    module_case_f1 = f'/modules.php?name=sud_delo&name_op=r&delo_id=1540006&case_type=0&new=0&u1_case__CASE_NUMBERSS={id_text}&delo_table=u1_case&u1_case__ENTRY_DATE1D={adm_date}&u1_case__ENTRY_DATE2D={adm_date}'

    link_to_search_case = court_website + module_case_f1

    # checking captcha
    if captcha == "True":
        captcha_addition = _get_captcha_from_soup_f1(soup_captcha)
        link_to_search_case += captcha_addition

    try:
        browser.get(link_to_search_case)
        # explicitly waiting for the results table
        el_found = sudrfparser._explicit_wait(browser,"ID","tablcont",6)
        soup = BeautifulSoup(browser.page_source, 'html.parser')

        # no case found (no results or error)
        if soup.find("table", {"id": "tablcont"}) == None:
            # TO-DO
                    
            # if there is a table with results
            else:
                case_link = _get_case_link_f1(soup)
                if len(case_link) > 1:
                    # TO-DO
                else:
                    # get case info
                    browser.get(case_link[0])
                    soup_case = BeautifulSoup(browser.page_source, 'html.parser')

                    # getting case data
                    content = soup.find('div', {'class': 'contentt'})
                    # TO-DO



def find_case_by_id(path_to_driver:str,id_text:str,court_website:str,adm_date:str,srv_num:list,path_to_save="") -> str:
    '''
    '''

    browser = sudrfparser._set_browser(path_to_driver)
    link_to_site = court_website + "/modules.php?name=sud_delo&srv_num=1&name_op=sf&delo_id=1540005"

    try:
        browser.get(link_to_site)
        content_found = sudrfparser._explicit_wait(browser,"ID","modSdpContent",6)
        # additional time if explicit wait fails
        time.sleep(3)

        if content_found == True:

            soup = BeautifulSoup(browser.page_source, 'html.parser')

            form_and_captcha = sudrfparser._check_form_and_captcha(soup)
            form_type = form_and_captcha["form_type"]
            captcha = form_and_captcha["captcha"]

             # parser for form1
            if form_type == "form1" and captcha == "False":
                # TO-DO

            if form_type == "form1" and captcha == "True":
                # TO-DO

            # parser for form2
            if form_type == "form2" and captcha == "False":
                # TO-DO

            if form_type == "form2" and captcha == "True":
                # TO-DO

        else:
            results = f"Failed to load content of {court_website}"

        
    except WebDriverException:
        results = f"{court_website} cannot be parsed. Web driver error"
    
    browser.close()
    
    return results

def get_cases_by_keywords(path_to_driver:str, cases_links:dict, cases_ids_to_ignore=[], path_to_save="") -> str:
    '''
    path_to_driver: str, path to Chrome driver;
    cases_links: dict, links to cases (results from get_cases_links)
    cases_ids_to_ignore: list, cases ID, which won't be saved (for example, when results for these cases were already saved before), default is [];
    path_to_save: str, directory where to save files and logs, default is "";
    Saves 3 files: (1) json with parsed cases, (2) txt with cased ids that were requested (so that they can be ignored during the next requests, pass this list to "cases_ids_to_ignore"), (3) txt with logs;
    Returns status str
    '''

    browser = sudrfparser._set_browser(path_to_driver)

    results = {}
    logs = []
    # generating a request ID based on local time
    timestamp = time.localtime()
    request_id = f"{timestamp[3]}-{timestamp[4]}-{timestamp[5]}-{timestamp[2]}-{timestamp[1]}-{timestamp[0]}"

    for keyword, cases_by_keyword in cases_links.items():
        for case in cases_by_keyword["cases"]:
            case_id = case["case_id_uid"]

            if case_id not in cases_ids_to_ignore:
                # encoding case url
                link = urllib.parse.quote(case["case_url"],safe='/:#,=&')
                # opening each case in a new tab, so they load properly
                browser.execute_script("window.open('');")
                browser.switch_to.window(browser.window_handles[1])
                browser.get(link)

                check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","documentInner",20)
                # additional wait
                time.sleep(3)

                if check_content == True:

                    # captcha handler
                    captcha_window = browser.find_elements(By.XPATH, '//*[@id="modalWindow_capchaDialog"]')
                    
                    if len(captcha_window) > 0:
                        # captcha is broken, so sending any nymber will work
                        browser.find_element(By.XPATH, '//*[@id="capchaDialog"]/input').send_keys(1)
                        # clicking on the send button
                        browser.find_element(By.CLASS_NAME, 'ui-button-text').click()
                        # additional wait
                        time.sleep(5)
                        check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","documentInner", 20)
                        # additional wait
                        time.sleep(3)
                        # saving the case
                        # subfunction to collect case text and metadata
                        case_data = _get_case_text_and_metadata(browser)
                        # writing results
                        results[case_id] = case_data
                        cases_ids_to_ignore.append(case_id)

                    # no captcha    
                    else:
                        # saving the case
                        case_data = _get_case_text_and_metadata(browser)
                        # writing results
                        results[case_id] = case_data
                        cases_ids_to_ignore.append(case_id)

                else:
                # a case is not loaded
                    logs.append(f"Case {case_id} failed to load")

                # closing the tab with case and switching to the first tab
                browser.close()
                browser.switch_to.window(browser.window_handles[0])

            else:
                logs.append(f"Case {case_id} was already saved")

    browser.close()

    # saving files

    # save results in json
    results_file_name = f"{path_to_save}/results_{request_id}.json"
    with open(results_file_name, 'w') as jf:
        json.dump(results, jf, ensure_ascii=False)

    # save cases_ids_to_ignore as txt if there are any
    if len(cases_ids_to_ignore) > 0:
        cases_ids_to_ignore_file_name = f"{path_to_save}/cases_ids_to_ignore_{request_id}.txt"
        with open(cases_ids_to_ignore_file_name,'w') as txt_file:
            for case_id in cases_ids_to_ignore:
                txt_file.write(case_id + "\n")

    # save logs as txt if there are any
    if len(logs) > 0:
        logs_file_name = f"{path_to_save}/logs_{request_id}.txt"
        with open(logs_file_name,'w') as txt_file:
            for log in logs:
                txt_file.write(log + "\n")

    return f"Job is finished. Results are saved in {path_to_save}"