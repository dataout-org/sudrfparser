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
    ### id_text
    id_text = browser.find_element(By.XPATH,'//*[@id="bookmark0"]/ul[1]/li[1]/div/table/tbody/tr[1]/td[2]/div/div/span').text
    case_info["metadata"]["id_text"] = id_text
    ### judge
    judge = browser.find_element(By.XPATH,'//*[@id="bookmark0"]/ul[1]/li[2]/div/table/tbody/tr[1]/td[2]/div/div/a').text
    case_info["metadata"]["judge"] = judge
    ### decision_result
    decision_result = browser.find_element(By.XPATH,'//*[@id="bookmark0"]/ul[1]/li[1]/div/table/tbody/tr[8]/td[2]/div/div/span').text
    case_info["metadata"]["decision_result"] = decision_result
    
    # switching to the tab "Движение по делу" to get adm_date
    ### adm_date
    browser.find_element(By.XPATH,'//*[@id="cardContainer"]/div[2]/div/div/ul/li[2]/label').click()
    adm_date = browser.find_element(By.XPATH,'//*[@id="bookmark1"]/ul[1]/li/div/table/tbody/tr[1]/td[2]/div/div/span').text
    case_info["metadata"]["adm_date"] = adm_date

    # switching to the case text "Судебные акты": click on the tab first, then switch to frame
    browser.find_element(By.XPATH, '//*[@id="cardContainer"]/div[2]/div/div/ul/li[3]/label').click()
    browser.switch_to.frame(browser.find_element(By.TAG_NAME, "iframe"))
    soup = BeautifulSoup(browser.page_source, 'html.parser')
    # save text
    case_text = soup.find("span").text.replace('"','\'').replace('\xa0','')
    case_info["case_text"] = case_text

    return case_info

def get_cases_by_keywords(path_to_driver:str, keywords:list, start_date:str, end_date:str, cases_ids_to_ignore=[], path_to_save="") -> str:
    '''
    path_to_driver: str, path to Chrome driver;
    keywords: list, keywords (words and phrases) to search for in cases texts, for example, ["ключевое слово", "ещё одно слово"];
    start_date: str, format 'YYYY-MM-DD', for example, '2023-01-30';
    end_date: str, format 'YYYY-MM-DD', for example, '2023-12-31';
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

    for keyword in keywords:

        results_per_keyword = {}
        cases_per_keyword = []
        all_ids_per_keyword = []

        # shaping a request link per keyword
        request_link = '''https://bsr.sudrf.ru/bigs/portal.html#{"type":"MULTIQUERY","multiqueryRequest":{"queryRequests":[{"type":"Q","queryRequestRole":"SIMPLE","request":"{\\"query\\":\\"''' + keyword + '''\\",\\"type\\":\\"NEAR\\",\\"mode\\":\\"SIMPLE\\"}","operator":"AND"},{"type":"Q","request":"{\\"mode\\":\\"EXTENDED\\",\\"typeRequests\\":[{\\"fieldRequests\\":[{\\"name\\":\\"case_user_doc_entry_date\\",\\"operator\\":\\"B\\",\\"query\\":\\"''' + start_date + '''T00:00:00\\",\\"sQuery\\":\\"''' + end_date + '''T00:00:00\\",\\"fieldName\\":\\"case_user_doc_entry_date\\"}],\\"mode\\":\\"AND\\",\\"name\\":\\"common\\",\\"typesMode\\":\\"AND\\"}]}","operator":"AND","queryRequestRole":"CATEGORIES"}]},"sorts":[{"field":"score","order":"desc"}],"simpleSearchFieldsBundle":"ug","noOrpho":false,"rows":20}'''

        # encoding the request link
        request_link_encoded = urllib.parse.quote(request_link,safe='/:#,=&')

        browser.get(request_link_encoded)
        # checking if the content is loaded and visible
        check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","resultsList", 60)

        if check_content == True:

            soup = BeautifulSoup(browser.page_source, 'html.parser')

            # check if results are found
            result_list = soup.find("ul",{"id":"resultsList"}).find_all("li")

            if result_list[0].text == "Ничего не найдено":
                results_per_keyword = {"n_cases":0}
                logs.append(f"No results for the keyword {keyword}")

            else:
                all_links = []
                # appending all links from the first page
                for li in result_list:
                    all_links.append(li.find("a",{"class":"resultHeader"})["href"])

                n_cases = int(soup.find("div",{"id":"resultCount"})["data-total"])
                # n_pages
                n_pages = n_cases // 20 # max 20 cases per page
                if n_cases % 20 != 0: # if there's a leftover, add a page
                    n_pages += 1

                # iterate over all pages if there are multiple pages and collect all links
                if n_pages > 1:
                
                    # get a session uid
                    session_uid = re.search("(\\d|\\w){8}-((\\d|\\w){4}-){3}(\\d|\\w){12}",all_links[0])[0]

                    for i in range(20,n_cases,20):

                        pagination = '''https://bsr.sudrf.ru/bigs/portal.html#{"start":'''+ str(i) + ''',"rows":20,"uid":"''' + session_uid + '''","type":"MULTIQUERY","multiqueryRequest":{"queryRequests":[{"type":"Q","queryRequestRole":"SIMPLE","request":"{\\"query\\":\\"''' + keyword + '''\\",\\"type\\":\\"NEAR\\",\\"mode\\":\\"SIMPLE\\"}","operator":"AND"},{"type":"Q","request":"{\\"mode\\":\\"EXTENDED\\",\\"typeRequests\\":[{\\"fieldRequests\\":[{\\"name\\":\\"case_user_doc_entry_date\\",\\"operator\\":\\"B\\",\\"query\\":\\"''' + start_date + '''T00:00:00\\",\\"sQuery\\":\\"''' + end_date + '''T00:00:00\\",\\"fieldName\\":\\"case_user_doc_entry_date\\"}],\\"mode\\":\\"AND\\",\\"name\\":\\"common\\",\\"typesMode\\":\\"AND\\"}]}","operator":"AND","queryRequestRole":"CATEGORIES"}]},"sorts":[{"field":"score","order":"desc"}],"simpleSearchFieldsBundle":"ug","noOrpho":false,"facet":{"field":["type"]},"facetLimit":21,"additionalFields":["court_document_documentype1","court_case_entry_date","court_case_result_date","court_subject_rf","court_name_court","court_document_law_article","court_case_result","case_user_document_type","case_user_doc_entry_date","case_user_doc_result_date","case_doc_subject_rf","case_user_doc_court","case_doc_instance","case_document_category_article","case_user_doc_result","case_user_entry_date","m_case_user_type","m_case_user_sub_type","ora_main_law_article"],"hlFragSize":1000,"groupLimit":3,"woBoost":false}'''

                        # encoding the request link
                        pagination_encoded = urllib.parse.quote(pagination,safe='/:#,=&')

                        browser.get(pagination_encoded)
                        # checking if the content is loaded and visible
                        check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","resultsList",20)

                        soup = BeautifulSoup(browser.page_source, 'html.parser')
                        # expanding all_links
                        result_list = soup.find("ul",{"id":"resultsList"}).find_all("li")
                        for li in result_list:
                            all_links.append(li.find("a",{"class":"resultHeader"})["href"])

                #TO-DO: save all links per keyword in a separate file

                # opening cases in a new tab

                for link in all_links:

                    case_id = re.search("(id=.*&shard=)",link)[0].replace("id=","").replace("&shard=","")
                    all_ids_per_keyword.append(case_id)

                    # do not parse the case info if it was already parsed before with a different keyword
                    if case_id not in cases_ids_to_ignore:

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
                                # additional wait before refresh
                                time.sleep(6)
                                browser.refresh()
                                check_content = sudrfparser._explicit_wait(browser,"CLASS_NAME","documentInner", 20)
                                # additional wait
                                time.sleep(3)
                                # saving the case
                                # subfunction to collect case text and metadata
                                case_data = _get_case_text_and_metadata(browser)
                                case_data["case_id_uid"] = case_id
                                cases_ids_to_ignore.append(case_id)
                                # write results to cases_per_keyword
                                cases_per_keyword.append(case_data)

                            # no captcha    
                            else:
                                # saving the case
                                # subfunction to collect case text and metadata
                                case_data = _get_case_text_and_metadata(browser)
                                case_data["case_id_uid"] = case_id
                                cases_ids_to_ignore.append(case_id)
                                # write results to cases_per_keyword
                                cases_per_keyword.append(case_data)

                        else:
                        # a case is not loaded
                            logs.append(f"Case has failed to load; {case_id}; {link}")
                            # TO DO: more actions needed to continue (reopen page again)

                        # closing the tab with case and switching to the first tab
                        browser.close()
                        browser.switch_to.window(browser.window_handles[0])

                    else:
                        logs.append(f"Case {case_id} was already saved")

                results_per_keyword = {"n_cases":n_cases, "cases":cases_per_keyword, "all_cases_ids":all_ids_per_keyword}

        else:
            results_per_keyword = "request_failed"
            logs.append(f"Search for the keyword {keyword} has failed")

        results[keyword] = results_per_keyword

    browser.close()

    # saving files

    # save results in json
    results_file_name = f"{path_to_save}/results_{start_date.split('-')[0]}_{request_id}.json"
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